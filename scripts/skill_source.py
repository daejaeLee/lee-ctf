#!/usr/bin/env python3
"""Check or safely stage the pinned ctf-skills source without touching the vendor tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit, urlunsplit


DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_RELATIVE_PATH = Path(".ctf") / "skills.lock.json"
FULL_COMMIT = re.compile(r"[0-9a-fA-F]{40}")
TOP_LEVEL_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?")
FRONTMATTER_MAX_LINES = 128
FRONTMATTER_MAX_BYTES = 16 * 1024


class SkillSourceError(ValueError):
    """Raised when the pinned skill source cannot be checked or staged safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_lock(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except json.JSONDecodeError as exc:
        raise SkillSourceError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SkillSourceError(f"skills lock must be a JSON object: {path}")
    source = value.get("source")
    ref = value.get("ref")
    commit = value.get("resolved_commit")
    skills = value.get("skills")
    if not isinstance(source, str) or not source or source.startswith("-"):
        raise SkillSourceError("skills lock source must be a non-empty Git location")
    if not isinstance(ref, str) or not ref or ref.startswith("-"):
        raise SkillSourceError("skills lock ref must be a non-empty branch or tag")
    if not isinstance(commit, str) or not FULL_COMMIT.fullmatch(commit):
        raise SkillSourceError("skills lock resolved_commit must be a full Git commit")
    if (
        not isinstance(skills, list)
        or not skills
        or any(not isinstance(item, str) or not item for item in skills)
        or len(skills) != len(set(skills))
    ):
        raise SkillSourceError("skills lock skills must be a non-empty, duplicate-free string list")
    return value


def _display_source(source: str) -> str:
    """Remove URL credentials before a source is printed or written to a report."""

    parsed = urlsplit(source)
    if not parsed.scheme or not parsed.netloc:
        return source
    hostname = parsed.hostname or ""
    if parsed.port:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def _safe_git_detail(stderr: str, source: str) -> str:
    lines = stderr.strip().splitlines()
    if not lines:
        return ""
    return lines[-1].replace(source, _display_source(source))


def _run_git(arguments: Sequence[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0 or timeout_seconds > 600:
        raise SkillSourceError("Git timeout must be greater than 0 and no more than 600 seconds")
    try:
        return subprocess.run(
            ["git", *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise SkillSourceError("git executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SkillSourceError("Git operation timed out") from exc


def _ref_patterns(ref: str) -> list[str]:
    if ref.startswith("refs/"):
        patterns = [ref]
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            patterns.insert(0, f"{ref}^{{}}")
        return patterns
    return [f"refs/heads/{ref}", f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}"]


def _parse_remote_commit(output: str, patterns: Sequence[str]) -> str:
    refs: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.strip().split()
        if len(parts) != 2 or not FULL_COMMIT.fullmatch(parts[0]):
            continue
        refs[parts[1]] = parts[0].lower()
    for pattern in patterns:
        if pattern in refs:
            return refs[pattern]
    raise SkillSourceError("configured ref was not returned by git ls-remote")


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


def _assert_no_link_components(path: Path, boundary: Path) -> None:
    absolute_boundary = boundary.absolute()
    absolute_path = path.absolute()
    try:
        relative = absolute_path.relative_to(absolute_boundary)
    except ValueError as exc:
        raise SkillSourceError(f"staged path escapes payload boundary: {path}") from exc
    current = absolute_boundary
    if _is_link_like(current):
        raise SkillSourceError(f"staging boundary cannot be a link or junction: {current}")
    for part in relative.parts:
        current /= part
        if os.path.lexists(current) and _is_link_like(current):
            raise SkillSourceError(f"staged path cannot contain a link or junction: {current}")


def _sha256_file(path: Path) -> str:
    if _is_link_like(path):
        raise SkillSourceError(f"staged file cannot be a link or junction: {path}")
    lexical = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(lexical.st_mode):
        raise SkillSourceError(f"staged path must be a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino) != (lexical.st_dev, lexical.st_ino):
            raise SkillSourceError(f"staged file changed while opening: {path}")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    current = os.stat(path, follow_symlinks=False)
    identities = {
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns),
    }
    if len(identities) != 1:
        raise SkillSourceError(f"staged file changed while hashing: {path}")
    return digest.hexdigest()


def check_source(lock_path: str | Path, *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Return the pinned and current remote commit without mutating local state."""

    path = Path(lock_path).resolve()
    lock = _read_lock(path)
    source = str(lock["source"])
    ref = str(lock["ref"])
    current_commit = str(lock["resolved_commit"]).lower()
    patterns = _ref_patterns(ref)
    completed = _run_git(["ls-remote", "--exit-code", source, *patterns], timeout_seconds)
    if completed.returncode != 0:
        detail = _safe_git_detail(completed.stderr, source)
        suffix = f": {detail}" if detail else ""
        raise SkillSourceError(f"git ls-remote failed with exit {completed.returncode}{suffix}")
    remote_commit = _parse_remote_commit(completed.stdout, patterns)
    return {
        "source": _display_source(source),
        "ref": ref,
        "pinned_commit": current_commit,
        "remote_commit": remote_commit,
        "update_available": remote_commit != current_commit,
    }


def _frontmatter_name(path: Path) -> str:
    lines: list[str] = []
    total_bytes = 0
    end: int | None = None
    with path.open("rb") as handle:
        for index in range(FRONTMATTER_MAX_LINES + 1):
            remaining = FRONTMATTER_MAX_BYTES - total_bytes
            if remaining <= 0:
                raise SkillSourceError(
                    f"frontmatter exceeds {FRONTMATTER_MAX_BYTES} bytes: {path}"
                )
            raw_line = handle.readline(remaining + 1)
            if not raw_line:
                break
            if len(raw_line) > remaining:
                raise SkillSourceError(
                    f"frontmatter exceeds {FRONTMATTER_MAX_BYTES} bytes: {path}"
                )
            total_bytes += len(raw_line)
            try:
                line = raw_line.decode("utf-8").rstrip("\r\n")
            except UnicodeError as exc:
                raise SkillSourceError(f"SKILL.md must be valid UTF-8: {path}") from exc
            lines.append(line)
            if index == 0 and line != "---":
                raise SkillSourceError(f"missing YAML frontmatter: {path}")
            if index > 0 and line == "---":
                end = index
                break
    if end is None:
        raise SkillSourceError(
            f"frontmatter must close within {FRONTMATTER_MAX_LINES} lines: {path}"
        )

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or line[:1].isspace():
            continue
        match = TOP_LEVEL_KEY.fullmatch(line)
        if not match:
            raise SkillSourceError(f"invalid top-level frontmatter line: {path}")
        key, raw_value = match.groups()
        if key in fields:
            raise SkillSourceError(f"duplicate frontmatter key {key!r}: {path}")
        fields[key] = (raw_value or "").strip()
    name = fields.get("name", "").strip("\"'")
    description = fields.get("description", "").strip("\"'")
    if not name:
        raise SkillSourceError(f"frontmatter name is missing: {path}")
    if not description:
        raise SkillSourceError(f"frontmatter description is missing: {path}")
    return name


def _locate_payload_root(staging_root: Path, skills: Sequence[str]) -> Path:
    candidates = (staging_root, staging_root / "skills", staging_root / ".agents" / "skills")
    for candidate in candidates:
        if all((candidate / skill / "SKILL.md").is_file() for skill in skills):
            return candidate
    raise SkillSourceError("staged repository does not contain every locked skill")


def validate_staged_payload(
    staging_root: str | Path,
    skills: Sequence[str],
    support_files: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Validate expected skill entrypoints and hash their entire staged trees."""

    stage_lexical = Path(staging_root).absolute()
    _assert_no_link_components(stage_lexical, stage_lexical)
    stage = stage_lexical.resolve()
    payload_lexical = _locate_payload_root(stage, skills)
    _assert_no_link_components(payload_lexical, stage)
    payload = payload_lexical.resolve()
    try:
        payload.relative_to(stage)
    except ValueError as exc:
        raise SkillSourceError("skill payload resolves outside the staging tree") from exc

    discovered_skills: set[str] = set()
    for child in payload.iterdir():
        _assert_no_link_components(child, payload)
        if child.is_dir() and (child / "SKILL.md").is_file():
            _assert_no_link_components(child / "SKILL.md", payload)
            discovered_skills.add(child.name)
    unexpected = discovered_skills - set(skills)
    if unexpected:
        raise SkillSourceError(
            f"staged repository contains unexpected skills: {', '.join(sorted(unexpected))}"
        )

    entries: dict[str, str] = {}
    for skill in sorted(skills):
        skill_root = payload / skill
        entrypoint_lexical = skill_root / "SKILL.md"
        _assert_no_link_components(entrypoint_lexical, payload)
        entrypoint = entrypoint_lexical.resolve()
        try:
            entrypoint.relative_to(payload)
        except ValueError as exc:
            raise SkillSourceError(f"skill entrypoint escapes staging tree: {skill}") from exc
        declared_name = _frontmatter_name(entrypoint)
        if declared_name != skill:
            raise SkillSourceError(f"{skill} declares mismatched name {declared_name!r}")
        for current_text, directory_names, file_names in os.walk(
            skill_root, topdown=True, followlinks=False
        ):
            current = Path(current_text)
            for name in sorted(directory_names):
                _assert_no_link_components(current / name, payload)
            for name in sorted(file_names):
                path = current / name
                _assert_no_link_components(path, payload)
                resolved = path.resolve()
                try:
                    resolved.relative_to(payload)
                except ValueError as exc:
                    raise SkillSourceError(f"staged file escapes payload tree: {path}") from exc
                entries[resolved.relative_to(payload).as_posix()] = _sha256_file(resolved)

    staged_support: list[dict[str, str]] = []
    installed_prefix = ".agents/skills/"
    for item in support_files:
        installed_path = item.get("path") if isinstance(item, dict) else None
        if not isinstance(installed_path, str) or not installed_path.startswith(installed_prefix):
            raise SkillSourceError("locked support file path must be under .agents/skills")
        relative = installed_path[len(installed_prefix) :]
        source_relative = "LICENSE" if relative == "LICENSE.ctf-skills" else relative
        source_lexical = payload / source_relative
        _assert_no_link_components(source_lexical, payload)
        source_path = source_lexical.resolve()
        try:
            source_path.relative_to(payload)
        except ValueError as exc:
            raise SkillSourceError(f"support file escapes staged payload: {source_relative}") from exc
        if not source_path.is_file():
            raise SkillSourceError(f"staged support file is missing: {source_relative}")
        staged_support.append(
            {
                "source_path": source_relative,
                "destination_path": installed_path,
                "sha256": _sha256_file(source_path),
            }
        )

    tree_digest = hashlib.sha256()
    for relative_path, file_hash in sorted(entries.items()):
        tree_digest.update(relative_path.encode("utf-8"))
        tree_digest.update(b"\x00")
        tree_digest.update(file_hash.encode("ascii"))
        tree_digest.update(b"\n")
    return {
        "payload_root": payload,
        "skill_count": len(skills),
        "file_count": len(entries),
        "tree_sha256": tree_digest.hexdigest(),
        "support_files": staged_support,
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
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


def stage_source(
    lock_path: str | Path,
    staging_dir: str | Path,
    *,
    workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Clone and validate an update under ``.cache``; never promote it."""

    workspace = Path(workspace_root).resolve()
    allowed_root = (workspace / ".cache").resolve()
    try:
        allowed_root.relative_to(workspace)
    except ValueError as exc:
        raise SkillSourceError("workspace .cache resolves outside the workspace") from exc
    stage = Path(staging_dir)
    if not stage.is_absolute():
        stage = workspace / stage
    stage = stage.resolve()
    try:
        stage.relative_to(allowed_root)
    except ValueError as exc:
        raise SkillSourceError(f"staging directory must be inside {allowed_root}") from exc
    if stage.exists():
        raise SkillSourceError(f"staging directory already exists: {stage}")
    if stage == allowed_root:
        raise SkillSourceError("staging directory must be a child of workspace .cache")
    stage.parent.mkdir(parents=True, exist_ok=True)

    lock = _read_lock(Path(lock_path).resolve())
    check = check_source(lock_path, timeout_seconds=min(timeout_seconds, 60.0))
    ref = str(lock["ref"])
    clone_ref = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
    completed = _run_git(
        [
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            clone_ref,
            "--",
            str(lock["source"]),
            str(stage),
        ],
        timeout_seconds,
    )
    if completed.returncode != 0:
        detail = _safe_git_detail(completed.stderr, str(lock["source"]))
        suffix = f": {detail}" if detail else ""
        raise SkillSourceError(f"git clone failed with exit {completed.returncode}{suffix}")

    head = _run_git(["-C", str(stage), "rev-parse", "HEAD"], min(timeout_seconds, 30.0))
    if head.returncode != 0 or not FULL_COMMIT.fullmatch(head.stdout.strip()):
        raise SkillSourceError("unable to resolve staged repository HEAD")
    staged_commit = head.stdout.strip().lower()
    if staged_commit != check["remote_commit"]:
        raise SkillSourceError("source ref changed while staging; discard this stage and retry")

    raw_support = lock.get("support_files", [])
    if not isinstance(raw_support, list):
        raise SkillSourceError("skills lock support_files must be a list")
    validation = validate_staged_payload(
        stage,
        [str(item) for item in lock["skills"]],
        raw_support,
    )
    locked_tree = str(lock.get("tree_sha256") or "").lower()
    if (
        not check["update_available"]
        and locked_tree
        and validation["tree_sha256"] != locked_tree
    ):
        raise SkillSourceError(
            "unchanged source commit does not reproduce the locked skill tree; do not promote"
        )
    if not check["update_available"]:
        expected_support = {
            str(item.get("path")): str(item.get("sha256") or "").lower()
            for item in raw_support
            if isinstance(item, dict)
        }
        for staged_support in validation["support_files"]:
            expected_hash = expected_support.get(staged_support["destination_path"], "")
            if expected_hash and staged_support["sha256"] != expected_hash:
                raise SkillSourceError(
                    "unchanged source commit does not reproduce locked support files; do not promote"
                )
    payload_root = Path(validation["payload_root"])
    report = {
        "schema_version": 1,
        "status": "validated-not-promoted",
        "staged_at": _utc_now(),
        "source": check["source"],
        "ref": check["ref"],
        "previous_commit": check["pinned_commit"],
        "staged_commit": staged_commit,
        "update_available": check["update_available"],
        "payload_root": payload_root.relative_to(stage).as_posix() or ".",
        "skill_count": validation["skill_count"],
        "file_count": validation["file_count"],
        "tree_sha256": validation["tree_sha256"],
        "support_files": validation["support_files"],
        "local_files_preserved": len(lock.get("local_files", [])),
        "promotion_performed": False,
    }
    report_path = stage / ".ctf-stage-report.json"
    _write_json_atomic(report_path, report)
    report["stage"] = str(stage)
    report["report_path"] = str(report_path)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", default=str(DEFAULT_WORKSPACE_ROOT))
    parser.add_argument("--lock", help="defaults to <workspace>/.ctf/skills.lock.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="compare the pinned commit with the remote ref")
    check.add_argument("--timeout", type=float, default=20.0)
    check.add_argument("--strict", action="store_true", help="return 1 when an update exists")

    stage = subparsers.add_parser("stage", help="clone and validate under .cache without promotion")
    stage.add_argument("--timeout", type=float, default=180.0)
    stage.add_argument("--staging-dir", help="must be a new directory under <workspace>/.cache")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = Path(args.workspace_root).resolve()
    lock_path = Path(args.lock).resolve() if args.lock else workspace / DEFAULT_LOCK_RELATIVE_PATH
    try:
        if args.command == "check":
            result = check_source(lock_path, timeout_seconds=args.timeout)
            state = "update-available" if result["update_available"] else "current"
            print(f"state: {state}")
            print(f"ref: {result['ref']}")
            print(f"pinned: {result['pinned_commit']}")
            print(f"remote: {result['remote_commit']}")
            return 1 if args.strict and result["update_available"] else 0

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        staging_dir = args.staging_dir or str(Path(".cache") / f"ctf-skills-stage-{timestamp}")
        result = stage_source(
            lock_path,
            staging_dir,
            workspace_root=workspace,
            timeout_seconds=args.timeout,
        )
        print(f"stage: {result['stage']}")
        print(f"commit: {result['staged_commit']}")
        print(f"validated: {result['skill_count']} skills, {result['file_count']} files")
        print("promotion: not performed")
        return 0
    except (OSError, SkillSourceError) as exc:
        print(f"skill source error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
