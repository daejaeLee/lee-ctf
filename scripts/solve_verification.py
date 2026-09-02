#!/usr/bin/env python3
"""Run a challenge solver and record a secret-safe reproducibility proof."""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
REPORT_RELATIVE_PATH = Path("evidence") / "solve-verification.json"
INPUT_MANIFEST_RELATIVE_PATH = Path("evidence") / "input-manifest.json"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
WINDOWS_CREATE_SUSPENDED = 0x00000004
FLAG_REGEX_MAX_BYTES = 8 * 1024
FLAG_MATCH_TIMEOUT_SECONDS = 2.0
FLAG_CANDIDATE_MAX_BYTES = 4 * 1024
PROTECTED_EXCLUDED_TOP_LEVEL = frozenset({"input", "solve", "work", "output", ".local"})
PROTECTED_EXCLUDED_FILES = frozenset(
    {REPORT_RELATIVE_PATH.as_posix(), "challenge.json"}
)
LEAK_SCAN_EXCLUDED_FILES = frozenset(
    {
        REPORT_RELATIVE_PATH.as_posix(),
        "work/.ctf-challenge.lock",
        "work/.ctf-import.lock",
    }
)


class VerificationError(ValueError):
    """Raised when a challenge cannot be verified safely."""


class _WindowsJob:
    """Kill an assigned Windows process tree when the job handle closes."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtResumeProcess.restype = wintypes.LONG
        ntdll.RtlNtStatusToDosError.argtypes = [wintypes.LONG]
        ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        information = ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(information), ctypes.sizeof(information)
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            kernel32.CloseHandle(handle)
            raise error
        self._ctypes = ctypes
        self._kernel32 = kernel32
        self._ntdll = ntdll
        self._handle = handle

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        process_handle = self._ctypes.c_void_p(int(process._handle))  # type: ignore[attr-defined]
        if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise self._ctypes.WinError(self._ctypes.get_last_error())

    def resume(self, process: subprocess.Popen[bytes]) -> None:
        process_handle = self._ctypes.c_void_p(int(process._handle))  # type: ignore[attr-defined]
        status = self._ntdll.NtResumeProcess(process_handle)
        if status != 0:
            error = self._ntdll.RtlNtStatusToDosError(status)
            raise self._ctypes.WinError(error)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


class _PosixContainment:
    """Track and kill solver descendants, including Linux setsid/double-fork escapes."""

    PR_SET_CHILD_SUBREAPER = 36

    def __init__(self) -> None:
        self._linux = sys.platform.startswith("linux")
        self._baseline_children: set[int] = set()
        if not self._linux:
            return
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        libc.prctl.restype = ctypes.c_int
        if libc.prctl(self.PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        self._baseline_children = self._direct_children(os.getpid())

    @staticmethod
    def _direct_children(pid: int) -> set[int]:
        task_root = Path(f"/proc/{pid}/task")
        children: set[int] = set()
        try:
            task_directories = list(task_root.iterdir())
        except OSError:
            return children
        for task in task_directories:
            try:
                raw = (task / "children").read_text(encoding="ascii")
            except OSError:
                continue
            for value in raw.split():
                if value.isdecimal():
                    children.add(int(value))
        return children

    def _descendants(self, roots: set[int]) -> set[int]:
        descendants: set[int] = set()
        pending = list(roots)
        while pending:
            pid = pending.pop()
            if pid in descendants or pid <= 0 or pid == os.getpid():
                continue
            descendants.add(pid)
            pending.extend(self._direct_children(pid) - descendants)
        return descendants

    def terminate(self, process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        if not self._linux:
            return

        # Orphans are reparented to this verifier because it is a subreaper.
        # Repeat the sweep so a descendant cannot win a fork/exit race.
        for _attempt in range(8):
            adopted = self._direct_children(os.getpid()) - self._baseline_children
            targets = self._descendants(adopted | {process.pid})
            targets.discard(process.pid)
            for pid in sorted(targets, reverse=True):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
            for pid in targets:
                try:
                    os.waitpid(pid, os.WNOHANG)
                except (ChildProcessError, OSError):
                    pass
            remaining = self._direct_children(os.getpid()) - self._baseline_children
            remaining.discard(process.pid)
            if not remaining:
                break
            time.sleep(0.01)


@dataclass
class _StreamCapture:
    retained: bytearray = field(default_factory=bytearray)
    byte_count: int = 0
    digest: Any = field(default_factory=hashlib.sha256)
    error: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    """In-memory result; ``candidate`` is intentionally excluded from JSON."""

    verified: bool
    candidate: str | None
    report: dict[str, Any]
    report_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def metadata_scope_sha256(metadata: dict[str, Any]) -> str:
    """Hash challenge scope while ignoring mutable solve-status fields."""

    scoped = {key: value for key, value in metadata.items() if key not in {"status", "solved_at"}}
    encoded = json.dumps(
        scoped,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _snapshot_file(path: Path) -> tuple[int, str]:
    if _is_link_like(path):
        raise VerificationError(f"links are not allowed in verified paths: {path}")
    lexical = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(lexical.st_mode):
        raise VerificationError(f"verified path must be a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino) != (lexical.st_dev, lexical.st_ino):
            raise VerificationError(f"file changed while opening it for verification: {path}")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    current = os.stat(path, follow_symlinks=False)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    identity_current = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    if identity_before != identity_after or identity_after != identity_current:
        raise VerificationError(f"file changed while it was being verified: {path}")
    return after.st_size, digest.hexdigest()


def _sha256_file(path: Path) -> str:
    return _snapshot_file(path)[1]


def _tree_sha256(entries: dict[str, dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for relative, record in sorted(entries.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _portable_path_key(value: str) -> str:
    return "/".join(
        unicodedata.normalize("NFKC", part).casefold()
        for part in PurePosixPath(value).parts
    )


def _snapshot_tree(
    root: Path,
    *,
    prefix: str,
    excluded_top_level_directories: frozenset[str] = frozenset(),
    excluded_relative_files: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    if not root.exists():
        return {}
    if not root.is_dir() or _is_link_like(root):
        raise VerificationError(f"verified tree must be a regular directory: {root}")
    entries: dict[str, dict[str, Any]] = {}
    portable_paths: dict[str, str] = {}

    def register(relative: str) -> None:
        key = _portable_path_key(relative)
        previous = portable_paths.get(key)
        if previous is not None and previous != relative:
            raise VerificationError(
                f"verified tree has a portable path collision: {previous!r} and {relative!r}"
            )
        portable_paths[key] = relative

    for current_text, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_text)
        current_relative = current.relative_to(root)
        directory_names.sort()
        file_names.sort()
        retained_directories: list[str] = []
        for name in directory_names:
            path = current / name
            if _is_link_like(path):
                raise VerificationError(f"links are not allowed in verified trees: {path}")
            relative = (current_relative / name).as_posix()
            register(relative)
            if current == root and name in excluded_top_level_directories:
                continue
            retained_directories.append(name)
        directory_names[:] = retained_directories
        for name in file_names:
            path = current / name
            if _is_link_like(path):
                raise VerificationError(f"links are not allowed in verified trees: {path}")
            relative = path.relative_to(root).as_posix()
            register(relative)
            if relative in excluded_relative_files:
                continue
            size, digest = _snapshot_file(path)
            key = (PurePosixPath(prefix) / PurePosixPath(relative)).as_posix()
            entries[key] = {"size": size, "sha256": digest}
    return entries


def protected_tree_state(challenge_root: str | Path) -> dict[str, Any]:
    """Hash tracked/curated challenge files that a solver must not mutate."""

    entries = _snapshot_tree(
        Path(challenge_root),
        prefix="challenge",
        excluded_top_level_directories=PROTECTED_EXCLUDED_TOP_LEVEL,
        excluded_relative_files=PROTECTED_EXCLUDED_FILES,
    )
    return {
        "file_count": len(entries),
        "tree_sha256": _tree_sha256(entries),
    }


def _optional_file_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    size, digest = _snapshot_file(path)
    return {"size": size, "sha256": digest}


def solve_tree_state(solve_root: str | Path) -> dict[str, Any]:
    """Hash every stable file in solve/, including pre-existing bytecode/cache paths."""

    root = Path(solve_root)
    entries = _snapshot_tree(root, prefix="solve")
    solver = entries.get("solve/solve.py")
    if solver is None:
        raise VerificationError(f"solver not found: {root / 'solve.py'}")
    return {
        "file_count": len(entries),
        "tree_sha256": _tree_sha256(entries),
        "solver_sha256": solver["sha256"],
    }


def _validate_input_state(directory: Path) -> dict[str, Any]:
    input_root = directory / "input"
    actual = _snapshot_tree(input_root, prefix="input")
    gitkeep = actual.get("input/.gitkeep")
    if gitkeep is not None and gitkeep["size"] == 0:
        del actual["input/.gitkeep"]

    manifest_path = directory / INPUT_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        if actual:
            raise VerificationError(
                "input artifacts exist without evidence/input-manifest.json; use the workspace import command"
            )
        return {
            "present": False,
            "sha256": None,
            "file_count": 0,
            "tree_sha256": _tree_sha256(actual),
        }
    try:
        manifest_path.resolve().relative_to(directory.resolve())
    except ValueError as exc:
        raise VerificationError("input manifest resolves outside the challenge directory") from exc
    if _is_link_like(manifest_path):
        raise VerificationError("input manifest cannot be a link or junction")
    manifest = _read_json_object(manifest_path)
    if manifest.get("schema_version") != 1 or manifest.get("algorithm") != "sha256":
        raise VerificationError("unsupported input manifest schema")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or manifest.get("file_count") != len(raw_files):
        raise VerificationError("input manifest file_count/files mismatch")

    expected: dict[str, dict[str, Any]] = {}
    ordered_paths: list[str] = []
    casefolded: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict) or set(raw) != {"path", "size", "sha256"}:
            raise VerificationError("invalid input manifest record")
        raw_path = raw.get("path")
        raw_size = raw.get("size")
        raw_hash = raw.get("sha256")
        if not isinstance(raw_path, str) or "\\" in raw_path:
            raise VerificationError("invalid input manifest path")
        relative = PurePosixPath(raw_path)
        if (
            relative.as_posix() != raw_path
            or relative.is_absolute()
            or len(relative.parts) < 2
            or relative.parts[0] != "input"
            or any(part in ("", ".", "..") for part in relative.parts)
        ):
            raise VerificationError("input manifest path is not normalized under input/")
        folded = _portable_path_key(raw_path)
        if folded in casefolded:
            raise VerificationError("duplicate input manifest path")
        casefolded.add(folded)
        if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size < 0:
            raise VerificationError("invalid input manifest size")
        if not isinstance(raw_hash, str) or not SHA256_PATTERN.fullmatch(raw_hash):
            raise VerificationError("invalid input manifest sha256")
        ordered_paths.append(raw_path)
        expected[raw_path] = {"size": raw_size, "sha256": raw_hash}
    if ordered_paths != sorted(ordered_paths, key=_portable_path_key):
        raise VerificationError("input manifest records are not in deterministic path order")
    if expected != actual:
        raise VerificationError("input artifacts do not match evidence/input-manifest.json")
    return {
        "present": True,
        "sha256": _sha256_file(manifest_path),
        "file_count": len(actual),
        "tree_sha256": _tree_sha256(actual),
    }


def _safe_output_parent(directory: Path, parent: Path) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    try:
        relative = parent.absolute().relative_to(directory.absolute())
    except ValueError as exc:
        raise VerificationError("verification output path escapes the challenge") from exc
    current = directory.absolute()
    for part in relative.parts:
        current = current / part
        if _is_link_like(current):
            raise VerificationError(f"verification output directory cannot be a link: {current}")
    try:
        parent.resolve().relative_to(directory.resolve())
    except ValueError as exc:
        raise VerificationError("verification output path resolves outside the challenge") from exc


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"JSON document must be an object: {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _resolve_challenge(workspace_root: Path, challenge: str | Path) -> Path:
    workspace_root = workspace_root.resolve()
    challenge_root = (workspace_root / "c").resolve()
    try:
        challenge_root.relative_to(workspace_root)
    except ValueError as exc:
        raise VerificationError("challenge root resolves outside the workspace") from exc
    candidate = Path(challenge)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    candidate = candidate.resolve()
    if candidate.is_file() and candidate.name == "challenge.json":
        candidate = candidate.parent
    try:
        candidate.relative_to(challenge_root)
    except ValueError as exc:
        raise VerificationError(f"challenge must be inside {challenge_root}") from exc
    if not (candidate / "challenge.json").is_file():
        raise VerificationError(f"challenge.json not found under {candidate}")
    return candidate


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    posix_containment: _PosixContainment | None = None,
) -> None:
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            if completed.returncode != 0 and process.poll() is None:
                process.kill()
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()
    else:
        if posix_containment is not None:
            posix_containment.terminate(process)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                if process.poll() is None:
                    process.kill()


def _run_bounded(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: float,
    max_output_bytes: int,
) -> dict[str, Any]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or timeout_seconds > 3600:
        raise VerificationError("timeout must be greater than 0 and no more than 3600 seconds")
    if (
        not isinstance(max_output_bytes, int)
        or isinstance(max_output_bytes, bool)
        or max_output_bytes < 1024
        or max_output_bytes > 128 * 1024 * 1024
    ):
        raise VerificationError("max output must be between 1 KiB and 128 MiB")

    creationflags = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_BREAKAWAY_FROM_JOB
        | WINDOWS_CREATE_SUSPENDED
        if os.name == "nt"
        else 0
    )
    posix_containment: _PosixContainment | None = None
    if os.name != "nt":
        try:
            posix_containment = _PosixContainment()
        except OSError as exc:
            raise VerificationError(f"unable to initialize solver containment: {exc}") from exc

    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.monotonic()
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        shell=False,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    windows_job: _WindowsJob | None = None
    if os.name == "nt":
        try:
            windows_job = _WindowsJob()
            windows_job.assign(process)
            windows_job.resume(process)
        except OSError as exc:
            if windows_job is not None:
                windows_job.close()
            _terminate_process_tree(process, posix_containment)
            process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            raise VerificationError(f"unable to contain solver process tree: {exc}") from exc
    assert process.stdout is not None and process.stderr is not None

    stdout_capture = _StreamCapture()
    stderr_capture = _StreamCapture()
    captures = ((process.stdout, stdout_capture), (process.stderr, stderr_capture))
    capture_lock = threading.Lock()
    retained_total = [0]
    observed_total = [0]
    output_limit_exceeded = threading.Event()

    def drain(stream: Any, capture: _StreamCapture) -> None:
        try:
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                capture.digest.update(chunk)
                with capture_lock:
                    capture.byte_count += len(chunk)
                    observed_total[0] += len(chunk)
                    remaining = max_output_bytes - retained_total[0]
                    if remaining > 0:
                        kept = chunk[:remaining]
                        capture.retained.extend(kept)
                        retained_total[0] += len(kept)
                    if observed_total[0] > max_output_bytes:
                        output_limit_exceeded.set()
        except (OSError, ValueError) as exc:
            capture.error = type(exc).__name__
        finally:
            stream.close()

    threads = [
        threading.Thread(target=drain, args=item, daemon=True)
        for item in captures
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    process_group_closed = False
    deadline = started + timeout_seconds
    while True:
        process_finished = process.poll() is not None
        readers_finished = not any(thread.is_alive() for thread in threads)
        if process_finished and windows_job is not None:
            windows_job.close()
            windows_job = None
            process_group_closed = True
        elif process_finished and os.name != "nt" and not process_group_closed:
            _terminate_process_tree(process, posix_containment)
            process_group_closed = True
        if process_finished and readers_finished:
            break
        if output_limit_exceeded.is_set():
            _terminate_process_tree(process, posix_containment)
            if windows_job is not None:
                windows_job.close()
                windows_job = None
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _terminate_process_tree(process, posix_containment)
            if windows_job is not None:
                windows_job.close()
                windows_job = None
            break
        time.sleep(0.01)

    if process.poll() is None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process, posix_containment)
            process.wait(timeout=5)
    if windows_job is not None:
        windows_job.close()
        windows_job = None
    for thread in threads:
        thread.join(timeout=5)
    if any(thread.is_alive() for thread in threads):
        for stream, _capture in captures:
            try:
                stream.close()
            except OSError:
                pass
        for thread in threads:
            thread.join(timeout=1)
    duration_ms = round((time.monotonic() - started) * 1000)

    return {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "output_limit_exceeded": output_limit_exceeded.is_set(),
        "duration_ms": duration_ms,
        "stdout": bytes(stdout_capture.retained),
        "stderr": bytes(stderr_capture.retained),
        "stdout_bytes": stdout_capture.byte_count,
        "stderr_bytes": stderr_capture.byte_count,
        "stdout_sha256": stdout_capture.digest.hexdigest(),
        "stderr_sha256": stderr_capture.digest.hexdigest(),
        "capture_error": stdout_capture.error or stderr_capture.error,
    }


def _decode_output(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16-le", "cp949"):
        try:
            return raw.decode(encoding).replace("\x00", "")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").replace("\x00", "")


def _flag_match_worker(encoded_pattern: str) -> int:
    """Internal killable regex worker; stdout is a private parent protocol."""

    try:
        raw_pattern = base64.urlsafe_b64decode(encoded_pattern.encode("ascii")).decode("utf-8")
        pattern = re.compile(raw_pattern)
        text = sys.stdin.buffer.read().decode("utf-8")
        matches: list[str] = []
        for match in pattern.finditer(text):
            candidate = match.group(0)
            if not candidate:
                print(json.dumps({"error": "empty_flag_candidate", "matches": []}))
                return 0
            if len(candidate.encode("utf-8")) > FLAG_CANDIDATE_MAX_BYTES:
                print(json.dumps({"error": "flag_candidate_too_long", "matches": []}))
                return 0
            if candidate not in matches:
                matches.append(candidate)
                if len(matches) >= 2:
                    break
        print(json.dumps({"error": None, "matches": matches}, ensure_ascii=False))
        return 0
    except (UnicodeError, ValueError, re.error):
        print(json.dumps({"error": "flag_match_worker_invalid_input", "matches": []}))
        return 0


def _flag_fullmatch_worker(encoded_pattern: str) -> int:
    """Internal killable fullmatch worker used by the manual flag command."""

    try:
        raw_pattern = base64.urlsafe_b64decode(encoded_pattern.encode("ascii")).decode("utf-8")
        pattern = re.compile(raw_pattern)
        candidate = sys.stdin.buffer.read().decode("utf-8")
        print(json.dumps({"error": None, "matched": pattern.fullmatch(candidate) is not None}))
        return 0
    except (UnicodeError, ValueError, re.error):
        print(json.dumps({"error": "flag_match_worker_invalid_input", "matched": False}))
        return 0


def flag_candidate_fullmatch(raw_pattern: str, candidate: str) -> tuple[bool, str | None]:
    if len(raw_pattern.encode("utf-8")) > FLAG_REGEX_MAX_BYTES:
        return False, "flag_regex_too_long"
    if len(candidate.encode("utf-8")) > FLAG_CANDIDATE_MAX_BYTES:
        return False, "flag_candidate_too_long"
    encoded_pattern = base64.urlsafe_b64encode(raw_pattern.encode("utf-8")).decode("ascii")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    worker = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--internal-flag-fullmatch", encoded_pattern],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=creationflags,
    )
    try:
        stdout, _stderr = worker.communicate(
            input=candidate.encode("utf-8"), timeout=FLAG_MATCH_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.communicate()
        return False, "flag_match_timeout"
    if worker.returncode != 0 or len(stdout) > 4096:
        return False, "flag_match_worker_failed"
    try:
        result = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False, "flag_match_worker_failed"
    if not isinstance(result, dict) or not isinstance(result.get("matched"), bool):
        return False, "flag_match_worker_failed"
    error = result.get("error")
    if error is not None:
        return False, str(error)
    return result["matched"], None


def _find_flag_candidates(raw_pattern: str, text: str) -> tuple[list[str], str | None]:
    encoded_pattern = base64.urlsafe_b64encode(raw_pattern.encode("utf-8")).decode("ascii")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    worker = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--internal-flag-match", encoded_pattern],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=creationflags,
    )
    try:
        stdout, _stderr = worker.communicate(
            input=text.encode("utf-8"), timeout=FLAG_MATCH_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.communicate()
        return [], "flag_match_timeout"
    if worker.returncode != 0 or len(stdout) > 64 * 1024:
        return [], "flag_match_worker_failed"
    try:
        result = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return [], "flag_match_worker_failed"
    if not isinstance(result, dict) or not isinstance(result.get("matches"), list):
        return [], "flag_match_worker_failed"
    error = result.get("error")
    if error is not None:
        return [], str(error)
    matches = result["matches"]
    if (
        len(matches) > 2
        or not all(isinstance(candidate, str) for candidate in matches)
        or any(len(candidate.encode("utf-8")) > FLAG_CANDIDATE_MAX_BYTES for candidate in matches)
    ):
        return [], "flag_match_worker_failed"
    return list(matches), None


def _candidate_needles(candidates: Sequence[str]) -> tuple[bytes, ...]:
    needles: set[bytes] = set()
    for candidate in candidates:
        for encoding in ("utf-8", "utf-16-le", "utf-16-be", "cp949"):
            try:
                encoded = candidate.encode(encoding)
            except UnicodeEncodeError:
                continue
            if encoded:
                needles.add(encoded)
    return tuple(sorted(needles, key=lambda item: (len(item), item)))


def _stable_file_contains(path: Path, needles: Sequence[bytes]) -> bool:
    if _is_link_like(path):
        raise VerificationError(f"links are not allowed in candidate leak scan: {path}")
    lexical = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(lexical.st_mode):
        raise VerificationError(f"candidate leak scan requires regular files: {path}")
    longest = max(len(needle) for needle in needles)
    overlap = max(0, longest - 1)
    found = False
    tail = b""
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino) != (lexical.st_dev, lexical.st_ino):
            raise VerificationError(f"file changed while opening candidate leak scan: {path}")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            combined = tail + chunk
            if any(needle in combined for needle in needles):
                found = True
            tail = combined[-overlap:] if overlap else b""
        after = os.fstat(handle.fileno())
    current = os.stat(path, follow_symlinks=False)
    identities = {
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns),
    }
    if len(identities) != 1:
        raise VerificationError(f"file changed during candidate leak scan: {path}")
    return found


def _candidate_leak_count(directory: Path, candidates: Sequence[str]) -> int:
    needles = _candidate_needles(candidates)
    if not needles:
        return 0
    portable_paths: dict[str, str] = {}
    leaks = 0

    def path_contains_candidate(relative: str) -> bool:
        return any(candidate in relative for candidate in candidates)

    for current_text, directory_names, file_names in os.walk(
        directory, topdown=True, followlinks=False
    ):
        current = Path(current_text)
        current_relative = current.relative_to(directory)
        retained: list[str] = []
        for name in sorted(directory_names):
            path = current / name
            if _is_link_like(path):
                raise VerificationError(f"links are not allowed in candidate leak scan: {path}")
            relative = (current_relative / name).as_posix()
            portable = _portable_path_key(relative)
            previous = portable_paths.get(portable)
            if previous is not None and previous != relative:
                raise VerificationError("portable path collision during candidate leak scan")
            portable_paths[portable] = relative
            if current == directory and name in {"input", ".local"}:
                continue
            if path_contains_candidate(relative):
                leaks += 1
            retained.append(name)
        directory_names[:] = retained
        for name in sorted(file_names):
            path = current / name
            if _is_link_like(path):
                raise VerificationError(f"links are not allowed in candidate leak scan: {path}")
            relative = path.relative_to(directory).as_posix()
            portable = _portable_path_key(relative)
            previous = portable_paths.get(portable)
            if previous is not None and previous != relative:
                raise VerificationError("portable path collision during candidate leak scan")
            portable_paths[portable] = relative
            if relative in LEAK_SCAN_EXCLUDED_FILES:
                continue
            if path_contains_candidate(relative):
                leaks += 1
            if _stable_file_contains(path, needles):
                leaks += 1
    return leaks


def verify_challenge(
    challenge: str | Path,
    *,
    workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    solver_args: Sequence[str] = (),
) -> VerificationResult:
    """Execute ``solve/solve.py`` and atomically write a redacted proof report."""

    workspace = Path(workspace_root).resolve()
    directory = _resolve_challenge(workspace, challenge)
    metadata_path = directory / "challenge.json"
    metadata = _read_json_object(metadata_path)
    solver_path = directory / "solve" / "solve.py"
    if not solver_path.is_file():
        raise VerificationError(f"solver not found: {solver_path}")
    resolved_solver = solver_path.resolve()
    try:
        resolved_solver.relative_to(directory)
    except ValueError as exc:
        raise VerificationError("solver resolves outside the challenge directory") from exc

    raw_pattern = metadata.get("flag_regex")
    if not isinstance(raw_pattern, str) or not raw_pattern:
        raise VerificationError("challenge metadata must contain a non-empty flag_regex")
    if len(raw_pattern.encode("utf-8")) > FLAG_REGEX_MAX_BYTES:
        raise VerificationError(f"challenge flag_regex exceeds {FLAG_REGEX_MAX_BYTES} bytes")
    try:
        re.compile(raw_pattern)
    except (re.error, RecursionError) as exc:
        raise VerificationError("challenge flag_regex is invalid") from exc

    solve_state = solve_tree_state(directory / "solve")
    input_state = _validate_input_state(directory)
    metadata_digest = metadata_scope_sha256(metadata)
    protected_state = protected_tree_state(directory)
    report_path = directory / REPORT_RELATIVE_PATH
    previous_report_state = _optional_file_state(report_path)
    normalized_solver_args = [str(value) for value in solver_args]
    command = [sys.executable, str(resolved_solver), *normalized_solver_args]
    execution = _run_bounded(command, directory, timeout_seconds, max_output_bytes)
    combined_output = _decode_output(execution["stdout"]) + "\n" + _decode_output(execution["stderr"])
    unique_candidates, match_error = _find_flag_candidates(raw_pattern, combined_output)

    state_changed = False
    try:
        state_changed = (
            solve_tree_state(directory / "solve") != solve_state
            or _validate_input_state(directory) != input_state
            or metadata_scope_sha256(_read_json_object(metadata_path)) != metadata_digest
            or protected_tree_state(directory) != protected_state
            or _optional_file_state(report_path) != previous_report_state
        )
    except (OSError, VerificationError):
        state_changed = True

    candidate_leak_count = 0
    if unique_candidates:
        try:
            candidate_leak_count = _candidate_leak_count(directory, unique_candidates)
        except (OSError, VerificationError):
            state_changed = True

    if execution["capture_error"]:
        reason = "output_capture_failed"
    elif execution["timed_out"]:
        reason = "solver_timeout"
    elif execution["output_limit_exceeded"]:
        reason = "output_limit_exceeded"
    elif match_error is not None:
        reason = match_error
    elif candidate_leak_count:
        reason = "candidate_leak_detected"
    elif state_changed:
        reason = "challenge_state_changed_during_execution"
    elif execution["exit_code"] != 0:
        reason = "solver_exit_nonzero"
    elif not unique_candidates:
        reason = "no_flag_match"
    elif len(unique_candidates) > 1:
        reason = "multiple_distinct_flag_matches"
    else:
        reason = "verified"

    verified = reason == "verified"
    candidate = unique_candidates[0] if verified else None
    relative_challenge = directory.relative_to(workspace).as_posix()
    arguments_blob = json.dumps(
        normalized_solver_args, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": reason,
        "verified": verified,
        "verified_at": _utc_now(),
        "challenge": relative_challenge,
        "metadata": {
            "path": "challenge.json",
            "scope_sha256": metadata_digest,
        },
        "solver": {
            "path": "solve/solve.py",
            "sha256": solve_state["solver_sha256"],
        },
        "solve_tree": {
            "path": "solve",
            "file_count": solve_state["file_count"],
            "tree_sha256": solve_state["tree_sha256"],
        },
        "protected_tree": {
            "path": ".",
            "file_count": protected_state["file_count"],
            "tree_sha256": protected_state["tree_sha256"],
        },
        "input_manifest": {
            "path": INPUT_MANIFEST_RELATIVE_PATH.as_posix(),
            "present": input_state["present"],
            "sha256": input_state["sha256"],
            "file_count": input_state["file_count"],
            "input_tree_sha256": input_state["tree_sha256"],
        },
        "execution": {
            "executable": Path(sys.executable).name,
            "arguments_count": len(normalized_solver_args),
            "arguments_sha256": _sha256_bytes(arguments_blob),
            "timeout_seconds": timeout_seconds,
            "max_output_bytes": max_output_bytes,
            "duration_ms": execution["duration_ms"],
            "exit_code": execution["exit_code"],
            "timed_out": execution["timed_out"],
            "output_limit_exceeded": execution["output_limit_exceeded"],
            "stdout_bytes": execution["stdout_bytes"],
            "stderr_bytes": execution["stderr_bytes"],
            "stdout_sha256": execution["stdout_sha256"],
            "stderr_sha256": execution["stderr_sha256"],
        },
        "candidate": {
            "distinct_matches": len(unique_candidates),
            "sha256": _sha256_bytes(candidate.encode("utf-8")) if candidate is not None else None,
            "leak_count": candidate_leak_count,
        },
    }
    _safe_output_parent(directory, report_path.parent)
    _write_json_atomic(report_path, report)
    return VerificationResult(
        verified=verified,
        candidate=candidate,
        report=report,
        report_path=report_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run solve/solve.py and write a redacted solve-verification proof."
    )
    parser.add_argument("challenge", help="challenge directory inside c/")
    parser.add_argument("--workspace-root", default=str(DEFAULT_WORKSPACE_ROOT))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-output-mb", type=float, default=4.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    if "--" in raw_arguments:
        separator = raw_arguments.index("--")
        parser_arguments = raw_arguments[:separator]
        solver_args = raw_arguments[separator + 1 :]
    else:
        parser_arguments = raw_arguments
        solver_args = []
    args = parser.parse_args(parser_arguments)
    try:
        try:
            max_output_bytes = round(args.max_output_mb * 1024 * 1024)
        except (OverflowError, ValueError) as exc:
            raise VerificationError("max output must be a finite number") from exc
        result = verify_challenge(
            args.challenge,
            workspace_root=args.workspace_root,
            timeout_seconds=args.timeout,
            max_output_bytes=max_output_bytes,
            solver_args=solver_args,
        )
    except (OSError, VerificationError) as exc:
        print(f"verification error: {exc}", file=sys.stderr)
        return 2
    digest = result.report["candidate"]["sha256"]
    if result.verified:
        print(f"verified: candidate_sha256={digest}")
        print(f"proof: {result.report_path}")
        return 0
    print(f"not verified: {result.report['status']}", file=sys.stderr)
    print(f"proof: {result.report_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--internal-flag-match":
        raise SystemExit(_flag_match_worker(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--internal-flag-fullmatch":
        raise SystemExit(_flag_fullmatch_worker(sys.argv[2]))
    raise SystemExit(main())
