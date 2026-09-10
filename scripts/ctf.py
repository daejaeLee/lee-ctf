#!/usr/bin/env python3
"""Small, dependency-free CLI for the lee-ctf workspace."""

from __future__ import annotations

import argparse
import errno
import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from check_skill_snapshot import validate_snapshot
from skill_source import check_source, stage_source
from solve_verification import (
    flag_candidate_fullmatch,
    metadata_scope_sha256,
    protected_tree_state,
    solve_tree_state,
    verify_challenge,
)


ROOT = Path(__file__).resolve().parents[1]
CTF_CONFIG = ROOT / ".ctf" / "config.json"
MODEL_ROUTING = ROOT / ".ctf" / "model-routing.json"
SKILLS_LOCK = ROOT / ".ctf" / "skills.lock.json"
SKILLS_MANIFEST = ROOT / ".ctf" / "skills.manifest.json"
SKILLS_ROOT = ROOT / ".agents" / "skills"
CHALLENGE_ROOT = ROOT / "c"
TEMPLATE_ROOT = ROOT / "templates" / "challenge"
LOCAL_FLAGS = ROOT / ".local" / "flags.json"
INPUT_MANIFEST = Path("evidence") / "input-manifest.json"
SOLVE_VERIFICATION = Path("evidence") / "solve-verification.json"
ROUTING_STATE = Path("work") / "routing-state.json"

DEFAULT_CATEGORIES = {
    "ai-ml": "ctf-ai-ml",
    "crypto": "ctf-crypto",
    "forensics": "ctf-forensics",
    "malware": "ctf-malware",
    "misc": "ctf-misc",
    "osint": "ctf-osint",
    "pwn": "ctf-pwn",
    "reverse": "ctf-reverse",
    "web": "ctf-web",
}

ALIASES = {
    "ai": "ai-ml",
    "ml": "ai-ml",
    "rev": "reverse",
    "re": "reverse",
    "forensic": "forensics",
}

FLAG_PATTERN = re.compile(rb"(?:[A-Za-z0-9_]{2,32})\{[^\r\n\x00{}]{1,256}\}")
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_json_atomic(path: Path, value: Any) -> None:
    """Atomically replace a JSON file after flushing its temporary copy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def project_config() -> dict[str, Any]:
    config = read_json(CTF_CONFIG, {}) or {}
    if not isinstance(config, dict):
        raise ValueError(f"project config must be a JSON object: {CTF_CONFIG}")
    return config


def category_map() -> dict[str, str]:
    categories = project_config().get("categories", DEFAULT_CATEGORIES)
    if not isinstance(categories, dict) or not categories:
        raise ValueError("project config categories must be a non-empty object")
    normalized = {str(key): str(value) for key, value in categories.items()}
    if any(not key or not value for key, value in normalized.items()):
        raise ValueError("project config categories cannot contain empty names")
    return normalized


def routing_policy() -> dict[str, Any]:
    policy = read_json(MODEL_ROUTING, {}) or {}
    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        raise ValueError("model routing policy must be a schema_version 1 JSON object")
    roles = policy.get("roles")
    thresholds = policy.get("thresholds")
    if not isinstance(roles, dict) or not isinstance(thresholds, dict):
        raise ValueError("model routing policy requires roles and thresholds objects")
    for name in ("scout", "worker", "analyst", "arbiter"):
        item = roles.get(name)
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key] for key in ("agent", "model", "reasoning_effort")):
            raise ValueError(f"model routing role is invalid: {name}")
    if not isinstance(thresholds.get("independent_failure_limit"), int) or not isinstance(thresholds.get("no_material_progress_seconds"), int):
        raise ValueError("model routing thresholds must be integers")
    return policy


def routing_state_path(challenge: Path) -> Path:
    return challenge / ROUTING_STATE


def initial_routing_state(challenge: Path) -> dict[str, Any]:
    metadata = read_json(challenge / "challenge.json", {}) or {}
    return {
        "schema_version": 1,
        "challenge": relative_display(challenge),
        "active_skill": str(metadata.get("skill") or "unknown"),
        "coordinator": "worker",
        "active_role": "worker",
        "attempts": [],
        "independent_primitives": [],
        "last_material_progress": None,
        "native_critical": False,
        "conflicting_hypotheses": False,
        "sol_outcome": None,
        "escalation_reason": None,
        "completion_state": None,
        "completion_reason": None,
    }


def load_routing_state(challenge: Path) -> dict[str, Any]:
    path = routing_state_path(challenge)
    state = read_json(path, None)
    if state is None:
        return initial_routing_state(challenge)
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError(f"invalid routing state: {relative_display(path)}")
    return state


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate_routing(state: dict[str, Any], policy: dict[str, Any], now: datetime | None = None) -> dict[str, str]:
    """Return the deterministic next routing action; never reset recorded failures."""
    now = now or datetime.now(timezone.utc)
    roles = policy["roles"]
    if state.get("sol_outcome") == "unresolved":
        return {"action": "ESCALATE_ASTRA", "role": "arbiter", "reason": "sol_unresolved"}
    if state.get("sol_outcome") == "decisive":
        return {"action": "RETURN_TERRA", "role": "worker", "reason": "sol_decisive_strategy"}
    if state.get("native_critical"):
        return {"action": "ESCALATE_SOL", "role": "analyst", "reason": "native_or_assembly_critical_path"}
    if state.get("conflicting_hypotheses"):
        return {"action": "ESCALATE_SOL", "role": "analyst", "reason": "conflicting_unresolved_hypotheses"}
    failures = len(set(str(item) for item in state.get("independent_primitives", [])))
    if failures >= policy["thresholds"]["independent_failure_limit"]:
        return {"action": "ESCALATE_SOL", "role": "analyst", "reason": "independent_failure_limit"}
    last_progress = parse_utc(state.get("last_material_progress"))
    if last_progress is not None and (now - last_progress).total_seconds() >= policy["thresholds"]["no_material_progress_seconds"]:
        return {"action": "ESCALATE_SOL", "role": "analyst", "reason": "no_material_progress_threshold"}
    return {"action": "CONTINUE_TERRA", "role": "worker", "reason": "within_routing_budget"}


def routing_summary(state: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    decision = evaluate_routing(state, policy)
    role = policy["roles"][decision["role"]]
    return {"decision": decision, "role": role, "failures": len(set(state.get("independent_primitives", [])))}


def update_routing_notes(challenge: Path, state: dict[str, Any], policy: dict[str, Any]) -> None:
    notes = challenge / "notes.md"
    if not notes.is_file():
        return
    summary = routing_summary(state, policy)
    decision, role = summary["decision"], summary["role"]
    marker_start, marker_end = "<!-- routing-state:start -->", "<!-- routing-state:end -->"
    block = "\n".join((marker_start, f"- Coordinator: Terra / medium", f"- Active skill: {state.get('active_skill', 'unknown')}", f"- Active model: {role['agent']} / {role['reasoning_effort']}", f"- Independent failures: {summary['failures']}", f"- Last material progress: {state.get('last_material_progress') or 'not recorded'}", f"- Escalation required: {'yes' if decision['action'].startswith('ESCALATE') else 'no'}", f"- Escalated to: {role['agent'] if decision['action'].startswith('ESCALATE') else 'none'}", f"- Escalation reason: {decision['reason']}", f"- Completion state: {state.get('completion_state') or 'IN_PROGRESS'}", f"- Completion reason: {state.get('completion_reason') or 'not recorded'}", marker_end))
    text = notes.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(marker_start) + r".*?" + re.escape(marker_end), re.S)
    if pattern.search(text):
        notes.write_text(pattern.sub(block, text, count=1), encoding="utf-8", newline="\n")


def persist_routing_state(challenge: Path, state: dict[str, Any], policy: dict[str, Any]) -> None:
    write_json_atomic(routing_state_path(challenge), state)
    update_routing_notes(challenge, state, policy)


def codex_agent_config() -> dict[str, tuple[str, str]]:
    path = ROOT / ".codex" / "config.toml"
    text = path.read_text(encoding="utf-8")
    found: dict[str, tuple[str, str]] = {}
    for agent in ("luna", "terra", "sol", "astra"):
        block = re.search(rf"^\[agents\.{agent}\]\s*$([\s\S]*?)(?=^\[|\Z)", text, re.M)
        if block is None:
            continue
        model = re.search(r'^model\s*=\s*"([^"]+)"\s*$', block.group(1), re.M)
        effort = re.search(r'^model_reasoning_effort\s*=\s*"([^"]+)"\s*$', block.group(1), re.M)
        if model and effort:
            found[agent] = (model.group(1), effort.group(1))
    return found


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value).strip(" .-")
    if not value:
        raise ValueError("name becomes empty after path sanitization")
    reserved_stem = value.split(".", 1)[0].rstrip(" .").upper()
    if reserved_stem in RESERVED_WINDOWS_NAMES:
        value = f"_{value}"
    return value


def normalize_category(value: str) -> str:
    value = value.strip().lower()
    value = ALIASES.get(value, value)
    categories = category_map()
    if value not in categories:
        raise ValueError(f"unknown category {value!r}; choose from {', '.join(categories)}")
    return value


def relative_display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def windows_path_to_wsl(path: Path) -> str | None:
    """Map a local drive path without passing backslashes through wslpath."""
    value = str(path.resolve())
    match = re.fullmatch(r"([A-Za-z]):[\\/]*(.*)", value)
    if match is None:
        return None
    drive, tail = match.groups()
    normalized_tail = tail.replace("\\", "/").lstrip("/")
    return f"/mnt/{drive.lower()}/{normalized_tail}".rstrip("/")


def challenge_dir(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    if candidate.is_file() and candidate.name == "challenge.json":
        candidate = candidate.parent
    try:
        candidate.relative_to(CHALLENGE_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"challenge must be inside {CHALLENGE_ROOT}") from exc
    if not (candidate / "challenge.json").is_file():
        raise ValueError(f"challenge.json not found under {candidate}")
    return candidate


def render_template(source: Path, destination: Path, values: dict[str, str]) -> None:
    text = source.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8", newline="\n")


def cmd_new(args: argparse.Namespace) -> int:
    category = normalize_category(args.category)
    event_slug = slugify(args.event)
    challenge_slug = slugify(args.name)
    destination = CHALLENGE_ROOT / event_slug / category / challenge_slug
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")

    skill = category_map()[category]
    port = args.port if args.port is not None else None
    legacy_url = getattr(args, "url", None)
    source_url = getattr(args, "source_url", None)
    target_url = getattr(args, "target_url", None)
    if legacy_url and (source_url or target_url):
        raise ValueError("--url cannot be combined with --source-url or --target-url")
    if legacy_url:
        source_url = legacy_url
        target_url = legacy_url
    target_parts = [
        part
        for part in (
            target_url,
            args.host and f"{args.host}:{port or ''}".rstrip(":"),
        )
        if part
    ]
    target = ", ".join(target_parts) if target_parts else "local artifacts only"
    relative_path = destination.relative_to(ROOT).as_posix()
    metadata = {
        "schema_version": 1,
        "id": relative_path.removeprefix("c/"),
        "event": args.event,
        "name": args.name,
        "slug": challenge_slug,
        "category": category,
        "skill": skill,
        "source_url": source_url or "",
        "target": {"url": target_url or "", "host": args.host or "", "port": port},
        "flag_regex": args.flag_regex,
        "status": "new",
        "created_at": utc_now(),
        "solved_at": None,
    }

    values = {
        "CHALLENGE_NAME": args.name,
        "EVENT": args.event,
        "CATEGORY": category,
        "SKILL": skill,
        "SOURCE_URL": source_url or "(not provided)",
        "TARGET": target,
        "RELATIVE_PATH": relative_path.replace("/", "\\"),
        "HOST_LITERAL": repr(args.host) if args.host else "None",
        "PORT_LITERAL": str(port) if port is not None else "None",
    }

    destination.mkdir(parents=True)
    write_json(destination / "challenge.json", metadata)
    for relative in (
        "README.md",
        "AGENTS.md",
        "notes.md",
        "writeup.md",
        "solve/solve.py",
    ):
        render_template(TEMPLATE_ROOT / relative, destination / relative, values)
    for relative in ("input/.gitkeep", "work/.gitkeep", "output/.gitkeep", "evidence/.gitkeep"):
        target_path = destination / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.touch()
    policy = routing_policy()
    persist_routing_state(destination, initial_routing_state(destination), policy)

    print(relative_display(destination))
    print(f"skill: {skill}")
    print(f"next: .\\ctf.ps1 import {relative_display(destination)} <artifact...>, then run triage")
    return 0


def print_routing_status(challenge: Path) -> int:
    policy = routing_policy()
    state = load_routing_state(challenge)
    summary = routing_summary(state, policy)
    decision, role = summary["decision"], summary["role"]
    print(f"Coordinator : terra/medium")
    print(f"Skill       : {state.get('active_skill', 'unknown')}")
    print(f"ActiveModel : {role['agent']}/{role['reasoning_effort']}")
    print(f"Failures    : {summary['failures']}")
    print(f"Decision    : {decision['action']}")
    print(f"Reason      : {decision['reason']}")
    print(f"Completion  : {state.get('completion_state') or 'IN_PROGRESS'}")
    if decision["action"].startswith("ESCALATE"):
        print(f"\nESCALATION REQUIRED\nTarget      : {role['agent']}/{role['reasoning_effort']}")
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    challenge = challenge_dir(args.challenge)
    policy = routing_policy()
    state = load_routing_state(challenge)
    persist_routing_state(challenge, state, policy)
    return print_routing_status(challenge)


def cmd_routing_status(args: argparse.Namespace) -> int:
    return print_routing_status(challenge_dir(args.challenge))


def cmd_checkpoint(args: argparse.Namespace) -> int:
    challenge = challenge_dir(args.challenge)
    policy = routing_policy()
    state = load_routing_state(challenge)
    before = evaluate_routing(state, policy)
    if before["action"] == "ESCALATE_SOL" and args.model != "sol":
        raise ValueError("Sol escalation is required; no other model can record another substantive attempt")
    if before["action"] == "ESCALATE_ASTRA" and args.model != "astra":
        raise ValueError("Astra escalation is required after unresolved Sol analysis")
    primitive = (args.primitive or args.strategy).strip().lower()
    if not primitive:
        raise ValueError("strategy or primitive cannot be empty")
    independent = bool(args.independent and args.result == "fail" and primitive not in state["independent_primitives"])
    if independent:
        state["independent_primitives"].append(primitive)
    if args.result == "progress":
        state["last_material_progress"] = utc_now()
    if args.native_critical:
        state["native_critical"] = True
    if args.conflicting_hypotheses:
        state["conflicting_hypotheses"] = True
    if args.sol_outcome:
        if args.model != "sol":
            raise ValueError("--sol-outcome requires --model sol")
        state["sol_outcome"] = args.sol_outcome
    state["attempts"].append({"at": utc_now(), "strategy": args.strategy, "primitive": primitive, "result": args.result, "independent": independent, "model": args.model, "evidence": args.evidence or ""})
    state["active_role"] = args.model
    after = evaluate_routing(state, policy)
    state["escalation_reason"] = after["reason"] if after["action"].startswith("ESCALATE") else None
    persist_routing_state(challenge, state, policy)
    return print_routing_status(challenge)


def cmd_complete(args: argparse.Namespace) -> int:
    challenge = challenge_dir(args.challenge)
    policy = routing_policy()
    if args.state not in policy["completion_states"]:
        raise ValueError("invalid terminal completion state")
    state = load_routing_state(challenge)
    state["completion_state"] = args.state
    state["completion_reason"] = args.reason
    persist_routing_state(challenge, state, policy)
    return print_routing_status(challenge)


def identify_magic(header: bytes, suffix: str) -> str:
    signatures = (
        (b"\x7fELF", "ELF"),
        (b"MZ", "PE/COFF"),
        (b"%PDF-", "PDF"),
        (b"\x89PNG\r\n\x1a\n", "PNG"),
        (b"\xff\xd8\xff", "JPEG"),
        (b"PK\x03\x04", "ZIP/Office/JAR/APK"),
        (b"\x1f\x8b", "gzip"),
        (b"7z\xbc\xaf\x27\x1c", "7-Zip"),
        (b"Rar!\x1a\x07", "RAR"),
        (b"\x0a\x0d\x0d\x0a", "PCAPNG"),
        (b"\xd4\xc3\xb2\xa1", "PCAP little-endian"),
        (b"\xa1\xb2\xc3\xd4", "PCAP big-endian"),
        (b"SQLite format 3\x00", "SQLite"),
        (b"RIFF", "RIFF/WAV/AVI"),
    )
    for signature, label in signatures:
        if header.startswith(signature):
            return label
    return suffix.lstrip(".").upper() or "unknown"


def sha256_file(path: Path) -> str:
    _size, digest, _identity = _hash_file_snapshot(path, reject_links=False)
    return digest


def locked_support_sha256(path: Path, relative: str) -> str:
    """Keep artifact hashing raw; only normalize Git's vendored-license checkout EOLs."""
    raw = sha256_file(path)
    if relative.replace("\\", "/") != ".agents/skills/LICENSE.ctf-skills":
        return raw
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _is_link_like(path: Path) -> bool:
    """Return true for symlinks, junctions, and other Windows reparse points."""
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


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(str(path))


def _stat_object_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    inode = int(getattr(info, "st_ino", 0))
    device = int(getattr(info, "st_dev", 0))
    if inode:
        return device, inode, 0, 0
    return (
        device,
        inode,
        int(info.st_size),
        int(getattr(info, "st_ctime_ns", round(info.st_ctime * 1_000_000_000))),
    )


def _stat_snapshot(info: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(getattr(info, "st_dev", 0)),
        int(getattr(info, "st_ino", 0)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", round(info.st_mtime * 1_000_000_000))),
    )


def _read_flags(*, reject_links: bool) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if reject_links:
        flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _hash_file_snapshot(
    path: Path,
    *,
    reject_links: bool,
) -> tuple[int, str, tuple[int, int, int, int]]:
    """Hash one stable opened file and return size, digest, and file identity."""
    if reject_links and _is_link_like(path):
        raise ValueError(f"file cannot be a link or junction: {path}")
    descriptor = os.open(path, _read_flags(reject_links=reject_links))
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"path is not a regular file: {path}")
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            after = os.fstat(descriptor)
        if _stat_snapshot(before) != _stat_snapshot(after):
            raise ValueError(f"file changed while it was being hashed: {path}")
        identity = _stat_object_identity(after)
        if reject_links:
            if _is_link_like(path):
                raise ValueError(f"file became a link or junction while hashing: {path}")
            try:
                current = os.stat(path, follow_symlinks=False)
            except OSError as exc:
                raise ValueError(f"file changed while it was being hashed: {path}") from exc
            if _stat_object_identity(current) != identity:
                raise ValueError(f"file was replaced while it was being hashed: {path}")
        return int(after.st_size), digest.hexdigest(), identity
    finally:
        os.close(descriptor)


def _safe_subdirectory(root: Path, relative: Path | str, *, create: bool = True) -> Path:
    """Resolve a real, non-reparse directory beneath a trusted root."""
    root_resolved = root.resolve(strict=True)
    relative_path = Path(relative)
    if relative_path.is_absolute() or any(part in ("", ".", "..") for part in relative_path.parts):
        raise ValueError(f"unsafe workspace subdirectory: {relative_path}")
    current = root_resolved
    for part in relative_path.parts:
        candidate = current / part
        if not _path_lexists(candidate):
            if not create:
                raise ValueError(f"required directory does not exist: {candidate}")
            try:
                candidate.mkdir()
            except FileExistsError:
                pass
        if _is_link_like(candidate):
            raise ValueError(f"workspace directory cannot be a link or junction: {candidate}")
        if not candidate.is_dir():
            raise ValueError(f"workspace path is not a directory: {candidate}")
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(f"workspace directory escapes {root_resolved}: {candidate}") from exc
        current = resolved
    return current


@contextmanager
def _exclusive_file_lock(path: Path, *, timeout_seconds: float = 30.0):
    """Hold a small advisory lock understood by both Windows and POSIX processes."""
    if _is_link_like(path):
        raise ValueError(f"lock file cannot be a link or junction: {path}")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    locked = False
    try:
        if _is_link_like(path):
            raise ValueError(f"lock file cannot be a link or junction: {path}")
        opened_identity = _stat_object_identity(os.fstat(descriptor))
        path_identity = _stat_object_identity(os.stat(path, follow_symlinks=False))
        if opened_identity != path_identity:
            raise ValueError(f"lock file was replaced while opening: {path}")
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for lock: {path}") from exc
                time.sleep(0.05)
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _validate_import_component(component: str) -> None:
    if component in ("", ".", ".."):
        raise ValueError(f"unsafe artifact path component: {component!r}")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', component):
        raise ValueError(f"artifact path is not portable to Windows: {component!r}")
    if component.endswith((" ", ".")):
        raise ValueError(f"artifact path cannot end in a space or dot: {component!r}")
    stem = component.split(".", 1)[0].rstrip(" .").upper()
    if stem in RESERVED_WINDOWS_NAMES:
        raise ValueError(f"artifact path uses a reserved Windows name: {component!r}")


def _validate_import_relative(relative: PurePosixPath, *, require_input_prefix: bool = False) -> None:
    if relative.is_absolute():
        raise ValueError(f"artifact path must be relative: {relative}")
    parts = relative.parts
    if require_input_prefix:
        if len(parts) < 2 or parts[0] != "input":
            raise ValueError(f"manifest artifact path must start with input/: {relative}")
        parts = parts[1:]
    if not parts:
        raise ValueError("artifact path cannot be empty")
    for component in parts:
        _validate_import_component(component)


def _artifact_key(relative: PurePosixPath) -> str:
    return "/".join(unicodedata.normalize("NFKC", part).casefold() for part in relative.parts)


def _path_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _scan_input(input_root: Path) -> tuple[list[Path], set[str]]:
    """List regular input files without following links and record occupied paths."""
    if not input_root.exists():
        return [], set()
    if not input_root.is_dir():
        raise ValueError(f"challenge input path is not a directory: {input_root}")
    if _is_link_like(input_root):
        raise ValueError(f"input directory cannot be a link or junction: {input_root}")

    files: list[Path] = []
    occupied: set[str] = set()
    for current_text, directory_names, file_names in os.walk(input_root, topdown=True, followlinks=False):
        current = Path(current_text)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            _validate_import_component(name)
            path = current / name
            if _is_link_like(path):
                raise ValueError(f"links and junctions are not allowed under input/: {path}")
            relative = PurePosixPath(path.relative_to(input_root).as_posix())
            key = _artifact_key(relative)
            if key in occupied:
                raise ValueError(f"case-insensitive artifact path collision under input/: {relative}")
            occupied.add(key)
        for name in file_names:
            _validate_import_component(name)
            path = current / name
            relative = PurePosixPath(path.relative_to(input_root).as_posix())
            key = _artifact_key(relative)
            if key in occupied:
                raise ValueError(f"case-insensitive artifact path collision under input/: {relative}")
            occupied.add(key)
            if _is_link_like(path) or not path.is_file():
                raise ValueError(f"input artifact must be a regular file: {path}")
            if relative == PurePosixPath(".gitkeep") and path.stat().st_size == 0:
                continue
            files.append(path)
    return files, occupied


def _record_for_input(path: Path, directory: Path) -> dict[str, Any]:
    relative = PurePosixPath(path.relative_to(directory).as_posix())
    _validate_import_relative(relative, require_input_prefix=True)
    size, digest, _identity = _hash_file_snapshot(path, reject_links=True)
    return {
        "path": relative.as_posix(),
        "size": size,
        "sha256": digest,
    }


def _read_input_manifest(path: Path) -> list[dict[str, Any]]:
    manifest = read_json(path, None)
    if not isinstance(manifest, dict):
        raise ValueError(f"input manifest must be a JSON object: {path}")
    if manifest.get("schema_version") != 1 or manifest.get("algorithm") != "sha256":
        raise ValueError(f"unsupported input manifest schema: {path}")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or manifest.get("file_count") != len(raw_files):
        raise ValueError(f"input manifest file_count/files mismatch: {path}")

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict) or set(raw) != {"path", "size", "sha256"}:
            raise ValueError(f"invalid input manifest record: {raw!r}")
        raw_path = raw.get("path")
        raw_size = raw.get("size")
        raw_hash = raw.get("sha256")
        if not isinstance(raw_path, str) or "\\" in raw_path:
            raise ValueError(f"invalid input manifest path: {raw_path!r}")
        relative = PurePosixPath(raw_path)
        if relative.as_posix() != raw_path:
            raise ValueError(f"input manifest path is not normalized: {raw_path!r}")
        _validate_import_relative(relative, require_input_prefix=True)
        key = _artifact_key(relative)
        if key in seen:
            raise ValueError(f"duplicate input manifest path: {raw_path}")
        seen.add(key)
        if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size < 0:
            raise ValueError(f"invalid input manifest size for {raw_path}")
        if not isinstance(raw_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
            raise ValueError(f"invalid input manifest sha256 for {raw_path}")
        records.append({"path": relative.as_posix(), "size": raw_size, "sha256": raw_hash})

    expected_order = sorted(records, key=lambda item: _artifact_key(PurePosixPath(item["path"])))
    if records != expected_order:
        raise ValueError(f"input manifest records are not in deterministic path order: {path}")
    return records


def _input_comparison(
    directory: Path,
    expected: list[dict[str, Any]],
) -> tuple[list[str], list[tuple[str, str, str]], list[str], list[dict[str, Any]], set[str]]:
    input_root = directory / "input"
    paths, occupied = _scan_input(input_root)
    actual_records = [_record_for_input(path, directory) for path in paths]
    actual_records.sort(key=lambda item: _artifact_key(PurePosixPath(item["path"])))
    expected_by_path = {item["path"]: item for item in expected}
    actual_by_path = {item["path"]: item for item in actual_records}

    missing = sorted(expected_by_path.keys() - actual_by_path.keys(), key=lambda item: item.casefold())
    extra = sorted(actual_by_path.keys() - expected_by_path.keys(), key=lambda item: item.casefold())
    changed: list[tuple[str, str, str]] = []
    for path in sorted(expected_by_path.keys() & actual_by_path.keys(), key=lambda item: item.casefold()):
        wanted = expected_by_path[path]
        found = actual_by_path[path]
        if wanted["size"] != found["size"] or wanted["sha256"] != found["sha256"]:
            changed.append((wanted["path"], wanted["sha256"], found["sha256"]))
    return missing, changed, extra, actual_records, occupied


def _collect_import_files(sources: list[str], input_root: Path) -> list[tuple[Path, PurePosixPath]]:
    planned: list[tuple[Path, PurePosixPath]] = []
    top_level_keys: set[str] = set()
    destination_nodes: dict[str, tuple[PurePosixPath, str]] = {}

    def claim_destination(relative: PurePosixPath, kind: str) -> None:
        key = _artifact_key(relative)
        previous = destination_nodes.get(key)
        if previous is not None:
            previous_path, previous_kind = previous
            if previous_path != relative or previous_kind != kind or kind == "file":
                raise ValueError(f"artifact destination collision: input/{relative.as_posix()}")
            return
        for parent in relative.parents:
            if parent == PurePosixPath("."):
                break
            parent_entry = destination_nodes.get(_artifact_key(parent))
            if parent_entry is not None and parent_entry[1] == "file":
                raise ValueError(f"artifact destination collision: input/{relative.as_posix()}")
        destination_nodes[key] = (relative, kind)

    for raw_source in sources:
        lexical = Path(raw_source).expanduser()
        if not lexical.exists():
            raise ValueError(f"artifact source does not exist: {lexical}")
        if _is_link_like(lexical):
            raise ValueError(f"artifact source cannot be a link or junction: {lexical}")
        source = lexical.resolve(strict=True)
        if _path_inside(source, input_root):
            raise ValueError(f"artifact source is already under challenge input/: {source}")
        _validate_import_component(source.name)
        top = PurePosixPath(source.name)
        top_key = _artifact_key(top)
        if top_key in top_level_keys:
            raise ValueError(f"artifact destination collision: input/{top.as_posix()}")
        top_level_keys.add(top_key)

        if source.is_file():
            claim_destination(top, "file")
            source_entries = [(source, top)]
        elif source.is_dir():
            source_entries: list[tuple[Path, PurePosixPath]] = []
            claim_destination(top, "directory")
            for current_text, directory_names, file_names in os.walk(source, topdown=True, followlinks=False):
                current = Path(current_text)
                directory_names.sort()
                file_names.sort()
                for name in directory_names:
                    _validate_import_component(name)
                    path = current / name
                    if _is_link_like(path):
                        raise ValueError(f"links and junctions are not allowed in artifact sources: {path}")
                    nested = PurePosixPath(path.relative_to(source).as_posix())
                    claim_destination(top / nested, "directory")
                for name in file_names:
                    _validate_import_component(name)
                    path = current / name
                    if _is_link_like(path) or not path.is_file():
                        raise ValueError(f"artifact source must contain only regular files: {path}")
                    nested = PurePosixPath(path.relative_to(source).as_posix())
                    relative = top / nested
                    _validate_import_relative(relative)
                    claim_destination(relative, "file")
                    source_entries.append((path, relative))
            if not source_entries:
                raise ValueError(f"artifact source directory contains no files: {source}")
        else:
            raise ValueError(f"artifact source must be a regular file or directory: {source}")

        planned.extend(source_entries)

    if not planned:
        raise ValueError("at least one artifact file is required")
    planned.sort(key=lambda item: _artifact_key(item[1]))
    return planned


def _copy_and_verify(source: Path, staged: Path) -> tuple[int, str]:
    if _is_link_like(source):
        raise ValueError(f"artifact source cannot be a link or junction: {source}")
    staged.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(source, _read_flags(reject_links=True))
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as source_handle, staged.open("xb") as staged_handle:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"artifact source must be a regular file: {source}")
            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                staged_handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            staged_handle.flush()
            os.fsync(staged_handle.fileno())
            after = os.fstat(descriptor)
        if _stat_snapshot(before) != _stat_snapshot(after) or size != after.st_size:
            raise ValueError(f"artifact source changed while it was being copied: {source}")
        if _is_link_like(source):
            raise ValueError(f"artifact source became a link or junction while copying: {source}")
        try:
            current = os.stat(source, follow_symlinks=False)
        except OSError as exc:
            raise ValueError(f"artifact source changed while it was being copied: {source}") from exc
        if _stat_object_identity(current) != _stat_object_identity(after):
            raise ValueError(f"artifact source was replaced while it was being copied: {source}")
    finally:
        os.close(descriptor)
    copied_hash = digest.hexdigest()
    staged_size, staged_hash, _identity = _hash_file_snapshot(staged, reject_links=True)
    if staged_size != size or staged_hash != copied_hash:
        raise OSError(f"staged artifact verification failed: {source}")
    return size, copied_hash


def _atomic_promote_no_replace(
    staged: Path,
    destination: Path,
    input_root: Path,
) -> tuple[Path, tuple[int, int, int, int]]:
    try:
        relative = destination.relative_to(input_root)
    except ValueError as exc:
        raise ValueError(f"artifact destination escapes input/: {destination}") from exc
    if len(relative.parts) == 1:
        parent = input_root.resolve(strict=True)
    else:
        parent = _safe_subdirectory(input_root, Path(*relative.parts[:-1]))
    destination = parent / relative.name
    staged_identity = _stat_object_identity(os.stat(staged, follow_symlinks=False))
    try:
        os.link(staged, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise ValueError(f"artifact destination already exists: {destination}") from exc
    except OSError as exc:
        raise OSError(f"atomic no-overwrite promotion failed for {destination}: {exc}") from exc
    try:
        destination_identity = _stat_object_identity(os.stat(destination, follow_symlinks=False))
        if destination_identity != staged_identity or _is_link_like(destination):
            raise OSError(f"promoted artifact identity mismatch: {destination}")
        confirmed_parent = (
            input_root.resolve(strict=True)
            if len(relative.parts) == 1
            else _safe_subdirectory(input_root, Path(*relative.parts[:-1]), create=False)
        )
        if confirmed_parent != parent:
            raise OSError(f"artifact destination parent changed during promotion: {destination}")
    except BaseException:
        try:
            current = os.stat(destination, follow_symlinks=False)
            if not _is_link_like(destination) and _stat_object_identity(current) == staged_identity:
                destination.unlink()
        except OSError:
            pass
        raise
    try:
        staged.unlink()
    except OSError:
        try:
            current = os.stat(destination, follow_symlinks=False)
            if not _is_link_like(destination) and _stat_object_identity(current) == staged_identity:
                destination.unlink()
        except OSError:
            pass
        raise
    return destination, staged_identity


def _write_input_manifest(path: Path, records: list[dict[str, Any]]) -> None:
    records = sorted(records, key=lambda item: _artifact_key(PurePosixPath(item["path"])))
    manifest = {
        "schema_version": 1,
        "algorithm": "sha256",
        "file_count": len(records),
        "files": records,
    }
    write_json_atomic(path, manifest)


def _rollback_import(
    promoted: list[tuple[Path, tuple[int, int, int, int]]],
    staged_files: list[tuple[Path, Path, PurePosixPath, int, str]],
    input_root: Path,
) -> None:
    for path, expected_identity in reversed(promoted):
        try:
            current = os.stat(path, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"WARN rollback could not inspect {path}: {exc}", file=sys.stderr)
            continue
        if _is_link_like(path) or _stat_object_identity(current) != expected_identity:
            print(f"WARN rollback left a replaced destination untouched: {path}", file=sys.stderr)
            continue
        try:
            path.unlink()
        except OSError as exc:
            print(f"WARN rollback could not remove {path}: {exc}", file=sys.stderr)
    for _source, _staged, relative, _size, _digest in reversed(staged_files):
        parent = input_root.joinpath(*relative.parts).parent
        while parent != input_root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _cleanup_import_staging(
    temporary_root: Path | None,
    expected_identity: tuple[int, int, int, int] | None,
) -> None:
    if temporary_root is None or not _path_lexists(temporary_root):
        return
    try:
        current = os.stat(temporary_root, follow_symlinks=False)
    except OSError as exc:
        print(f"WARN import staging cleanup could not inspect {temporary_root}: {exc}", file=sys.stderr)
        return
    if (
        expected_identity is None
        or _is_link_like(temporary_root)
        or not stat.S_ISDIR(current.st_mode)
        or _stat_object_identity(current) != expected_identity
    ):
        print(f"WARN import staging cleanup left a replaced directory untouched: {temporary_root}", file=sys.stderr)
        return
    try:
        for child in temporary_root.iterdir():
            if (
                not re.fullmatch(r"[0-9]{8}\.artifact", child.name)
                or _is_link_like(child)
                or not child.is_file()
            ):
                print(f"WARN import staging cleanup left an unexpected entry untouched: {child}", file=sys.stderr)
                continue
            child.unlink()
        temporary_root.rmdir()
    except OSError as exc:
        print(f"WARN import staging cleanup failed for {temporary_root}: {exc}", file=sys.stderr)


def cmd_import(args: argparse.Namespace) -> int:
    directory = challenge_dir(args.challenge)
    work_root = _safe_subdirectory(directory, "work")
    lock_path = work_root / ".ctf-challenge.lock"
    with _exclusive_file_lock(lock_path):
        input_root = _safe_subdirectory(directory, "input")
        evidence_root = _safe_subdirectory(directory, "evidence")
        work_root = _safe_subdirectory(directory, "work")
        manifest_path = evidence_root / INPUT_MANIFEST.name

        if manifest_path.exists():
            if _is_link_like(manifest_path):
                raise ValueError(f"input manifest cannot be a link or junction: {manifest_path}")
            baseline = _read_input_manifest(manifest_path)
            missing, changed, extra, _actual, occupied = _input_comparison(directory, baseline)
            if missing or changed or extra:
                raise ValueError("existing input does not match evidence/input-manifest.json; run verify-input")
        else:
            existing, occupied = _scan_input(input_root)
            baseline = [_record_for_input(path, directory) for path in existing]
            baseline.sort(key=lambda item: _artifact_key(PurePosixPath(item["path"])))
        manifest_existed = manifest_path.is_file()

        planned = _collect_import_files(args.sources, input_root)
        immediate_occupied = {
            _artifact_key(PurePosixPath(path.name))
            for path in input_root.iterdir()
        }
        for _source, relative in planned:
            top_key = _artifact_key(PurePosixPath(relative.parts[0]))
            if top_key in immediate_occupied:
                raise ValueError(f"artifact destination already exists: input/{relative.parts[0]}")
            destination = input_root.joinpath(*relative.parts)
            if not _path_inside(destination, input_root):
                raise ValueError(f"artifact destination escapes input/: {relative}")
            if _artifact_key(relative) in occupied or destination.exists() or _is_link_like(destination):
                raise ValueError(f"artifact destination already exists: input/{relative.as_posix()}")

        new_records: list[dict[str, Any]] = []
        promoted: list[tuple[Path, tuple[int, int, int, int]]] = []
        staged_files: list[tuple[Path, Path, PurePosixPath, int, str]] = []
        temporary_root: Path | None = None
        temporary_identity: tuple[int, int, int, int] | None = None
        manifest_write_started = False
        for _attempt in range(100):
            candidate = work_root / f"ctf-import-{secrets.token_hex(8)}"
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            temporary_root = candidate
            created = os.stat(candidate, follow_symlinks=False)
            if _is_link_like(candidate) or not stat.S_ISDIR(created.st_mode):
                raise ValueError(f"import staging path is not a real directory: {candidate}")
            temporary_identity = _stat_object_identity(created)
            break
        if temporary_root is None:
            raise OSError(f"unable to allocate an import staging directory under {work_root}")

        try:
            for index, (source, relative) in enumerate(planned):
                staged = temporary_root / f"{index:08d}.artifact"
                size, digest = _copy_and_verify(source, staged)
                staged_files.append((source, staged, relative, size, digest))

            if _safe_subdirectory(directory, "input") != input_root:
                raise ValueError("challenge input directory changed during import")
            for _source, staged, relative, size, digest in staged_files:
                destination = input_root.joinpath(*relative.parts)
                if not _path_inside(destination, input_root):
                    raise ValueError(f"artifact destination escapes input/: {relative}")
                destination, identity = _atomic_promote_no_replace(
                    staged, destination, input_root
                )
                promoted.append((destination, identity))
                new_records.append(
                    {
                        "path": (PurePosixPath("input") / relative).as_posix(),
                        "size": size,
                        "sha256": digest,
                    }
                )

            temporary_root.rmdir()
            temporary_root = None
            temporary_identity = None
            if _safe_subdirectory(directory, "evidence") != evidence_root:
                raise ValueError("challenge evidence directory changed during import")
            manifest_write_started = True
            _write_input_manifest(manifest_path, baseline + new_records)
        except BaseException:
            _rollback_import(promoted, staged_files, input_root)
            if manifest_write_started:
                try:
                    if manifest_existed:
                        _write_input_manifest(manifest_path, baseline)
                    elif manifest_path.is_file() and not _is_link_like(manifest_path):
                        manifest_path.unlink()
                except OSError as exc:
                    print(f"WARN input-manifest rollback failed: {exc}", file=sys.stderr)
            _cleanup_import_staging(temporary_root, temporary_identity)
            raise

        for record in new_records:
            print(f"IMPORTED {record['sha256'][:12]} {record['size']:>12} {record['path']}")
        print(f"manifest: {relative_display(manifest_path)} ({len(baseline) + len(new_records)} files)")
        return 0


def cmd_verify_input(args: argparse.Namespace) -> int:
    directory = challenge_dir(args.challenge)
    evidence_root = _safe_subdirectory(directory, "evidence", create=False)
    manifest_path = evidence_root / INPUT_MANIFEST.name
    if not manifest_path.is_file():
        print(f"[FAIL   ] input-manifest       missing: {relative_display(manifest_path)}")
        return 1
    if _is_link_like(manifest_path):
        raise ValueError(f"input manifest cannot be a link or junction: {manifest_path}")
    expected = _read_input_manifest(manifest_path)
    missing, changed, extra, actual, _occupied = _input_comparison(directory, expected)
    for path in missing:
        print(f"[MISSING] {path}")
    for path, wanted, found in changed:
        print(f"[CHANGED] {path} expected={wanted[:12]} actual={found[:12]}")
    for path in extra:
        print(f"[EXTRA  ] {path}")
    if missing or changed or extra:
        print(
            f"input verification failed: expected={len(expected)} actual={len(actual)} "
            f"missing={len(missing)} changed={len(changed)} extra={len(extra)}"
        )
        return 1
    print(f"input verified: {len(actual)} files; all SHA-256 hashes match")
    return 0


def _store_triage_candidates(directory: Path, candidates: set[str]) -> Path:
    try:
        local_relative = LOCAL_FLAGS.parent.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"local candidate store must remain inside {ROOT}") from exc
    local_root = _safe_subdirectory(ROOT, local_relative)
    store_path = local_root / "triage-candidates.json"
    if _is_link_like(store_path):
        raise ValueError(f"local candidate store cannot be a link or junction: {store_path}")
    with _exclusive_file_lock(local_root / ".triage-candidates.lock"):
        current = read_json(store_path, {}) or {}
        if not isinstance(current, dict):
            raise ValueError(f"local candidate store must be a JSON object: {store_path}")
        updated = dict(current)
        key = directory.relative_to(CHALLENGE_ROOT).as_posix()
        updated[key] = {
            "generated_at": utc_now(),
            "candidates": sorted(candidates),
        }
        write_json_atomic(store_path, updated)
    return store_path


def cmd_triage(args: argparse.Namespace) -> int:
    directory = challenge_dir(args.challenge)
    source = directory / "input"
    files = sorted(path for path in source.rglob("*") if path.is_file() and path.name != ".gitkeep")
    if not files:
        print(f"no input files under {relative_display(source)}")
        return 0

    hash_limit = args.hash_limit_mb * 1024 * 1024 if args.hash_limit_mb else None
    records: list[dict[str, Any]] = []
    candidates: set[str] = set()
    for path in files:
        size = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(64)
            if size <= args.flag_scan_mb * 1024 * 1024:
                handle.seek(0)
                blob = handle.read()
                for match in FLAG_PATTERN.findall(blob):
                    candidates.add(match.decode("utf-8", errors="replace"))
        digest = sha256_file(path) if hash_limit is None or size <= hash_limit else None
        records.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "size": size,
                "type": identify_magic(header, path.suffix),
                "sha256": digest,
            }
        )

    candidate_records = [
        {
            "sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
            "utf8_bytes": len(candidate.encode("utf-8")),
        }
        for candidate in sorted(candidates)
    ]
    local_candidate_store = _store_triage_candidates(directory, candidates)
    report = {
        "generated_at": utc_now(),
        "challenge": relative_display(directory),
        "files": records,
        "flag_candidates": candidate_records,
    }
    report_path = directory / "work" / "triage.json"
    write_json(report_path, report)
    print(f"{'TYPE':<22} {'SIZE':>12}  {'SHA256':<12} PATH")
    for record in records:
        short_hash = record["sha256"][:12] if record["sha256"] else "skipped"
        print(f"{record['type']:<22} {record['size']:>12}  {short_hash:<12} {record['path']}")
    if candidates:
        print("flag candidate digests (plaintext stored only under .local):")
        for candidate in candidate_records:
            print(f"  sha256={candidate['sha256']} utf8_bytes={candidate['utf8_bytes']}")
        print(f"local candidates: {relative_display(local_candidate_store)}")
    print(f"report: {relative_display(report_path)}")
    return 0


def iter_challenges() -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(CHALLENGE_ROOT.rglob("challenge.json")):
        try:
            result.append((path.parent, read_json(path, {})))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARN invalid metadata {relative_display(path)}: {exc}", file=sys.stderr)
    return result


def cmd_status(_args: argparse.Namespace) -> int:
    challenges = iter_challenges()
    if not challenges:
        print("no challenges")
        return 0
    print(f"{'STATUS':<10} {'CATEGORY':<12} {'SKILL':<16} CHALLENGE")
    for path, metadata in challenges:
        print(
            f"{metadata.get('status', '?'):<10} "
            f"{metadata.get('category', '?'):<12} "
            f"{metadata.get('skill', '?'):<16} "
            f"{relative_display(path)}"
        )
    return 0


def _candidate_sha256(candidate: str) -> str:
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()


def _current_inputs_match_manifest(directory: Path) -> tuple[bool, str]:
    try:
        evidence_root = _safe_subdirectory(directory, "evidence", create=False)
    except ValueError as exc:
        return False, str(exc)
    manifest_path = evidence_root / INPUT_MANIFEST.name
    if manifest_path.is_file():
        if _is_link_like(manifest_path):
            return False, f"input manifest cannot be a link or junction: {manifest_path}"
        expected = _read_input_manifest(manifest_path)
        missing, changed, extra, _actual, _occupied = _input_comparison(directory, expected)
        if missing or changed or extra:
            return (
                False,
                "input artifacts differ from the manifest "
                f"(missing={len(missing)}, changed={len(changed)}, extra={len(extra)})",
            )
        return True, "input artifacts match the manifest"
    existing, _occupied = _scan_input(directory / "input")
    if existing:
        return False, "input artifacts exist without evidence/input-manifest.json; use `ctf import`"
    return True, "challenge has no local input artifacts"


def _verification_matches_candidate(directory: Path, candidate: str) -> tuple[bool, str]:
    report_path = directory / SOLVE_VERIFICATION
    if not report_path.is_file():
        return False, f"verification proof not found: {relative_display(report_path)}"
    try:
        report = read_json(report_path, {})
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"verification proof is unreadable: {exc}"
    if not isinstance(report, dict) or report.get("verified") is not True or report.get("status") != "verified":
        return False, "verification proof is not successful"
    expected_challenge = directory.relative_to(ROOT).as_posix()
    if report.get("challenge") != expected_challenge:
        return False, "verification proof belongs to a different challenge"
    candidate_record = report.get("candidate")
    if not isinstance(candidate_record, dict) or candidate_record.get("sha256") != _candidate_sha256(candidate):
        return False, "candidate does not match the verified candidate digest"

    metadata_path = directory / "challenge.json"
    metadata_record = report.get("metadata")
    try:
        current_metadata = read_json(metadata_path, {})
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"challenge metadata is unreadable: {exc}"
    if (
        not isinstance(current_metadata, dict)
        or not isinstance(metadata_record, dict)
        or metadata_record.get("path") != "challenge.json"
        or metadata_record.get("scope_sha256") != metadata_scope_sha256(current_metadata)
    ):
        return False, "challenge target or verification scope changed after verification"

    solver_path = directory / "solve" / "solve.py"
    solver_record = report.get("solver")
    solve_tree_record = report.get("solve_tree")
    try:
        current_solve_tree = solve_tree_state(directory / "solve")
    except (OSError, ValueError) as exc:
        return False, f"solve tree is not verifiable: {exc}"
    if (
        not solver_path.is_file()
        or not isinstance(solver_record, dict)
        or solver_record.get("path") != "solve/solve.py"
        or solver_record.get("sha256") != current_solve_tree["solver_sha256"]
    ):
        return False, "solver changed after verification"
    if (
        not isinstance(solve_tree_record, dict)
        or solve_tree_record.get("path") != "solve"
        or solve_tree_record.get("file_count") != current_solve_tree["file_count"]
        or solve_tree_record.get("tree_sha256") != current_solve_tree["tree_sha256"]
    ):
        return False, "solve tree changed after verification"

    protected_record = report.get("protected_tree")
    try:
        current_protected_tree = protected_tree_state(directory)
    except (OSError, ValueError) as exc:
        return False, f"protected challenge tree is not verifiable: {exc}"
    if (
        not isinstance(protected_record, dict)
        or protected_record.get("path") != "."
        or protected_record.get("file_count") != current_protected_tree["file_count"]
        or protected_record.get("tree_sha256") != current_protected_tree["tree_sha256"]
    ):
        return False, "protected challenge files changed after verification"

    try:
        evidence_root = _safe_subdirectory(directory, "evidence", create=False)
    except ValueError as exc:
        return False, str(exc)
    manifest_path = evidence_root / INPUT_MANIFEST.name
    if manifest_path.is_file() and _is_link_like(manifest_path):
        return False, "input manifest is a link or junction"
    manifest_record = report.get("input_manifest")
    if not isinstance(manifest_record, dict):
        return False, "verification proof has no input-manifest record"
    was_present = manifest_record.get("present") is True
    if was_present != manifest_path.is_file():
        return False, "input manifest presence changed after verification"
    if was_present and manifest_record.get("sha256") != sha256_file(manifest_path):
        return False, "input manifest changed after verification"
    inputs_match, input_reason = _current_inputs_match_manifest(directory)
    if not inputs_match:
        return False, input_reason
    return True, "verified proof matches candidate, scope, protected files, solve tree, and input manifest"


def _store_flag(directory: Path, metadata: dict[str, Any], candidate: str) -> None:
    del metadata  # Metadata is re-read while holding the same lock as the flag store.
    try:
        local_relative = LOCAL_FLAGS.parent.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"local flag store must remain inside {ROOT}: {LOCAL_FLAGS}") from exc
    local_root = _safe_subdirectory(ROOT, local_relative)
    flags_path = local_root / LOCAL_FLAGS.name
    metadata_path = directory / "challenge.json"
    if _is_link_like(metadata_path):
        raise ValueError(f"challenge metadata cannot be a link or junction: {metadata_path}")

    with _exclusive_file_lock(local_root / ".flags.lock"):
        if _is_link_like(flags_path):
            raise ValueError(f"local flag store cannot be a link or junction: {flags_path}")
        flags_existed = flags_path.is_file()
        flags = read_json(flags_path, {}) or {}
        if not isinstance(flags, dict):
            raise ValueError(f"local flag store must be a JSON object: {flags_path}")
        current_metadata = read_json(metadata_path, {})
        if not isinstance(current_metadata, dict):
            raise ValueError(f"challenge metadata must be a JSON object: {metadata_path}")

        original_flags = dict(flags)
        updated_flags = dict(flags)
        key = directory.relative_to(CHALLENGE_ROOT).as_posix()
        recorded_at = utc_now()
        updated_flags[key] = {"flag": candidate, "recorded_at": recorded_at}
        updated_metadata = dict(current_metadata)
        updated_metadata["status"] = "solved"
        updated_metadata["solved_at"] = recorded_at

        try:
            write_json_atomic(flags_path, updated_flags)
            write_json_atomic(metadata_path, updated_metadata)
        except BaseException:
            rollback_errors: list[str] = []
            try:
                write_json_atomic(metadata_path, current_metadata)
            except OSError as exc:
                rollback_errors.append(f"metadata: {exc}")
            try:
                if flags_existed:
                    write_json_atomic(flags_path, original_flags)
                elif flags_path.is_file() and not _is_link_like(flags_path):
                    flags_path.unlink()
            except OSError as exc:
                rollback_errors.append(f"flags: {exc}")
            if rollback_errors:
                print(f"WARN local flag rollback failed: {'; '.join(rollback_errors)}", file=sys.stderr)
            raise


def cmd_flag(args: argparse.Namespace) -> int:
    directory = challenge_dir(args.challenge)
    candidate = args.value or getpass.getpass("Verified flag: ")
    if not candidate:
        raise ValueError("flag cannot be empty")
    work_root = _safe_subdirectory(directory, "work")
    with _exclusive_file_lock(work_root / ".ctf-challenge.lock"):
        metadata_path = directory / "challenge.json"
        if _is_link_like(metadata_path):
            raise ValueError(f"challenge metadata cannot be a link or junction: {metadata_path}")
        metadata = read_json(metadata_path, {})
        if not isinstance(metadata, dict):
            raise ValueError(f"challenge metadata must be a JSON object: {metadata_path}")
        raw_pattern = metadata.get("flag_regex") or r"(?i)[a-z0-9_]+\{[^\r\n}]+\}"
        if not isinstance(raw_pattern, str):
            raise ValueError("challenge flag_regex must be a string")
        if not args.allow_nonmatching:
            matched, match_error = flag_candidate_fullmatch(raw_pattern, candidate)
            if match_error is not None:
                raise ValueError(f"unable to safely evaluate flag_regex: {match_error}")
            if not matched:
                raise ValueError(
                    "candidate does not match flag_regex; use --allow-nonmatching only after manual verification"
                )
        verified, reason = _verification_matches_candidate(directory, candidate)
        if not verified and not getattr(args, "allow_unverified", False):
            raise ValueError(
                f"{reason}; run `ctf verify` or use --allow-unverified after manual reproduction"
            )
        _store_flag(directory, metadata, candidate)
    print(f"recorded locally and marked solved: {relative_display(directory)}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    directory = challenge_dir(args.challenge)
    try:
        max_output_bytes = round(args.max_output_mb * 1024 * 1024)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("max output must be a finite number") from exc
    solver_args = list(args.solver_args)
    if solver_args[:1] == ["--"]:
        solver_args = solver_args[1:]
    work_root = _safe_subdirectory(directory, "work")
    with _exclusive_file_lock(work_root / ".ctf-challenge.lock"):
        inputs_match, input_reason = _current_inputs_match_manifest(directory)
        if not inputs_match:
            raise ValueError(f"{input_reason}; run `ctf verify-input` before solving")
        result = verify_challenge(
            args.challenge,
            workspace_root=ROOT,
            timeout_seconds=args.timeout,
            max_output_bytes=max_output_bytes,
            solver_args=solver_args,
        )
        digest = result.report.get("candidate", {}).get("sha256")
        if not result.verified:
            print(f"not verified: {result.report.get('status', 'unknown')}", file=sys.stderr)
            print(f"proof: {relative_display(result.report_path)}", file=sys.stderr)
            return 1
        print(f"verified: candidate_sha256={digest}")
        print(f"proof: {relative_display(result.report_path)}")
        if args.record:
            if result.candidate is None:
                raise ValueError("verified result did not retain a candidate")
            proof_matches, proof_reason = _verification_matches_candidate(directory, result.candidate)
            if not proof_matches:
                raise ValueError(f"verification state changed before recording: {proof_reason}")
            metadata = read_json(directory / "challenge.json", {})
            _store_flag(directory, metadata, result.candidate)
            print(f"recorded locally and marked solved: {relative_display(directory)}")
    return 0


def cmd_agent_work(args: argparse.Namespace) -> int:
    directory = challenge_dir(args.challenge)
    agent_slug = slugify(args.name)
    agents_root = _safe_subdirectory(directory, Path("work") / "agents")
    destination = agents_root / agent_slug
    findings = destination / "findings.md"
    try:
        destination.mkdir()
        created = True
    except FileExistsError as exc:
        created = False
        if not args.reuse:
            raise ValueError(f"agent work directory already exists: {relative_display(destination)}") from exc
        if _is_link_like(destination) or not destination.is_dir():
            raise ValueError(f"agent work path is not a real directory: {relative_display(destination)}") from exc
        resolved = destination.resolve(strict=True)
        try:
            resolved.relative_to(agents_root)
        except ValueError as boundary_error:
            raise ValueError(f"agent work directory escapes {relative_display(agents_root)}") from boundary_error
        destination = resolved
        findings = destination / "findings.md"

    checked_destination = _safe_subdirectory(
        directory,
        Path("work") / "agents" / agent_slug,
        create=False,
    )
    if checked_destination != destination.resolve(strict=True):
        raise ValueError("agent work directory changed during creation")
    destination = checked_destination
    findings = destination / "findings.md"

    findings_text = "\n".join(
        (
            f"# Agent findings: {args.name}",
            "",
            "## Decisive facts",
            "",
            "## Hypotheses and tests",
            "",
            "## Failed paths",
            "",
            "## Next actions",
            "",
        )
    )
    try:
        with findings.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(findings_text)
    except FileExistsError:
        if not args.reuse or _is_link_like(findings) or not findings.is_file():
            if created:
                try:
                    destination.rmdir()
                except OSError:
                    pass
            raise ValueError(f"agent findings path already exists or is unsafe: {relative_display(findings)}")
    print(relative_display(destination))
    return 0


def cmd_skills_check(args: argparse.Namespace) -> int:
    result = check_source(SKILLS_LOCK, timeout_seconds=args.timeout)
    state = "update-available" if result["update_available"] else "current"
    print(f"state: {state}")
    print(f"ref: {result['ref']}")
    print(f"pinned: {result['pinned_commit']}")
    print(f"remote: {result['remote_commit']}")
    return 1 if args.strict and result["update_available"] else 0


def cmd_skills_stage(args: argparse.Namespace) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    staging_dir = args.staging_dir or str(Path(".cache") / f"ctf-skills-stage-{timestamp}")
    result = stage_source(
        SKILLS_LOCK,
        staging_dir,
        workspace_root=ROOT,
        timeout_seconds=args.timeout,
    )
    print(f"stage: {relative_display(Path(result['stage']))}")
    print(f"commit: {result['staged_commit']}")
    print(f"validated: {result['skill_count']} skills, {result['file_count']} files")
    print("promotion: not performed; review the staged report before an intentional snapshot update")
    return 0


def decode_command_output(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16-le", "cp949", "mbcs"):
        try:
            return raw.decode(encoding).replace("\x00", "").strip()
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace").replace("\x00", "").strip()


def run_probe(command: list[str], timeout: int = 8) -> tuple[int | None, str]:
    try:
        completed = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
        output = decode_command_output(completed.stdout + completed.stderr)
        return completed.returncode, output
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)


def validate_skill_entrypoints(skills_root: Path, skills: list[str]) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    for skill in skills:
        errors: list[str] = []
        path = skills_root / skill / "SKILL.md"
        if not path.is_file():
            results[skill] = ["SKILL.md missing"]
            continue
        text = path.read_text(encoding="utf-8")
        declared = re.search(r"(?m)^name:\s*[\"']?([^\s\"']+)", text)
        if not declared:
            errors.append("frontmatter name missing")
        elif declared.group(1) != skill:
            errors.append(f"declares name={declared.group(1)!r}")
        missing_links: set[str] = set()
        for link in re.findall(r"\]\(([^)]+)\)", text):
            target = unquote(link.split("#", 1)[0].strip().strip("<>"))
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            if not (path.parent / target).resolve().exists():
                missing_links.add(target)
        if missing_links:
            errors.append(f"missing links={', '.join(sorted(missing_links))}")
        results[skill] = errors
    return results


def skill_file_manifest(skills_root: Path, skills: list[str]) -> dict[str, str]:
    entries: dict[str, str] = {}
    for skill in sorted(skills):
        skill_root = skills_root / skill
        if not skill_root.is_dir():
            continue
        for path in sorted(item for item in skill_root.rglob("*") if item.is_file()):
            relative = path.relative_to(skills_root).as_posix()
            entries[relative] = sha256_file(path)
    return entries


def skill_tree_hash(entries: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, file_hash in sorted(entries.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def resolve_workspace_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def cmd_skills_manifest(args: argparse.Namespace) -> int:
    raw_lock = read_json(SKILLS_LOCK, {}) or {}
    if not isinstance(raw_lock, dict):
        raise ValueError(f"skills lock JSON root must be an object: {relative_display(SKILLS_LOCK)}")
    lock = raw_lock
    raw_skills = lock.get("skills", [])
    skills = [str(skill) for skill in raw_skills] if isinstance(raw_skills, list) else []
    if not skills or len(skills) != len(set(skills)):
        raise ValueError("skills lock must contain a non-empty, duplicate-free skills list")
    skills_root = resolve_workspace_path(args.skills_root)
    validation = validate_skill_entrypoints(skills_root, skills)
    errors = {skill: issues for skill, issues in validation.items() if issues}
    if errors:
        for skill, issues in errors.items():
            print(f"FAIL {skill}: {'; '.join(issues)}", file=sys.stderr)
        return 1

    entries = skill_file_manifest(skills_root, skills)
    commit = args.commit or str(lock.get("resolved_commit") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("source commit must be a full 40-character hexadecimal Git commit")
    commit = commit.lower()
    manifest = {
        "schema_version": 1,
        "source_commit": commit,
        "algorithm": "sha256 over sorted UTF-8 path, NUL, lowercase file sha256, LF",
        "file_count": len(entries),
        "tree_sha256": skill_tree_hash(entries),
        "files": entries,
    }
    output = resolve_workspace_path(args.output)
    write_json(output, manifest)
    print(f"manifest: {relative_display(output)}")
    print(f"files: {len(entries)}")
    print(f"tree_sha256: {manifest['tree_sha256']}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    failures = 0

    def emit(state: str, name: str, detail: str) -> None:
        nonlocal failures
        if state == "FAIL":
            failures += 1
        print(f"[{state:<7}] {name:<20} {detail}")

    snapshot = validate_snapshot(ROOT, SKILLS_LOCK)
    snapshot_detail = (
        f"{snapshot.skill_count} skills, {snapshot.file_count} locked files"
        if snapshot.ok
        else "; ".join(snapshot.errors[:3])
    )
    if not snapshot.ok and len(snapshot.errors) > 3:
        snapshot_detail += f"; +{len(snapshot.errors) - 3} more"
    emit("PASS" if snapshot.ok else "FAIL", "skill-snapshot", snapshot_detail)

    raw_lock = read_json(SKILLS_LOCK, {}) or {}
    if isinstance(raw_lock, dict):
        lock = raw_lock
    else:
        lock = {}
        emit("FAIL", "skills-lock", f"JSON root must be an object: {relative_display(SKILLS_LOCK)}")
    skills = [str(skill) for skill in lock.get("skills", [])]
    validation = validate_skill_entrypoints(SKILLS_ROOT, skills)
    for skill in skills:
        path = SKILLS_ROOT / skill / "SKILL.md"
        issues = validation.get(skill, ["validation did not run"])
        detail = relative_display(path) if not issues else f"{relative_display(path)}; {'; '.join(issues)}"
        emit("PASS" if not issues else "FAIL", f"skill:{skill}", detail)

    manifest_path = resolve_workspace_path(str(lock.get("manifest") or SKILLS_MANIFEST))
    manifest = read_json(manifest_path, {}) or {}
    actual_entries = skill_file_manifest(SKILLS_ROOT, skills)
    actual_tree = skill_tree_hash(actual_entries)
    raw_expected_entries = manifest.get("files", {}) if isinstance(manifest, dict) else {}
    expected_entries = raw_expected_entries if isinstance(raw_expected_entries, dict) else {}
    expected_tree = str(manifest.get("tree_sha256", "")) if isinstance(manifest, dict) else ""
    expected_count = manifest.get("file_count") if isinstance(manifest, dict) else None
    locked_tree = str(lock.get("tree_sha256", ""))
    manifest_commit = str(manifest.get("source_commit", "")) if isinstance(manifest, dict) else ""
    lock_commit = str(lock.get("resolved_commit", ""))
    manifest_valid = (
        bool(expected_entries)
        and expected_entries == actual_entries
        and expected_tree == actual_tree
        and expected_count == len(expected_entries)
        and locked_tree == actual_tree
        and manifest_commit == lock_commit
    )
    if manifest_valid:
        manifest_detail = f"{len(actual_entries)} files; tree={actual_tree[:16]}..."
    else:
        expected_paths = set(expected_entries)
        actual_paths = set(actual_entries)
        changed = sum(
            1
            for path in expected_paths & actual_paths
            if expected_entries.get(path) != actual_entries.get(path)
        )
        manifest_detail = (
            f"manifest mismatch: added={len(actual_paths - expected_paths)}, "
            f"removed={len(expected_paths - actual_paths)}, changed={changed}, "
            f"count_match={expected_count == len(expected_entries)}, "
            f"manifest_tree_match={expected_tree == actual_tree}, "
            f"lock_tree_match={locked_tree == actual_tree}, "
            f"commit_match={manifest_commit == lock_commit}"
        )
    emit("PASS" if manifest_valid else "FAIL", "skill-tree", manifest_detail)

    try:
        config = project_config()
        config_categories = category_map()
        config_valid = config.get("challenge_root") == CHALLENGE_ROOT.name and set(config_categories.values()) <= set(skills)
        config_detail = f"{len(config_categories)} categories; root={config.get('challenge_root')!r}"
        emit("PASS" if config_valid else "FAIL", "project-config", config_detail)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        emit("FAIL", "project-config", str(exc))

    try:
        policy = routing_policy()
        agents = codex_agent_config()
        role_agent = {"scout": "luna", "worker": "terra", "analyst": "sol", "arbiter": "astra"}
        routing_valid = all(
            policy["roles"][role]["agent"] == agent
            and agents.get(agent) == (policy["roles"][role]["model"], policy["roles"][role]["reasoning_effort"])
            for role, agent in role_agent.items()
        )
        emit("PASS" if routing_valid else "FAIL", "routing-contract", "policy roles match .codex agent models" if routing_valid else "policy/.codex agent model or effort drift")
        template_notes = (TEMPLATE_ROOT / "notes.md").read_text(encoding="utf-8")
        template_agents = (TEMPLATE_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        template_valid = all(marker in template_notes for marker in ("routing-state:start", "attempt-ledger:start")) and "MUST NOT relax" in template_agents
        emit("PASS" if template_valid else "FAIL", "routing-template", "challenge routing state and inheritance contract" if template_valid else "template routing contract is incomplete")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_valid = all(value in readme for value in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra")) and "mandatory" in readme.lower()
        emit("PASS" if docs_valid else "FAIL", "docs-config-sync", "README routing models and escalation documented" if docs_valid else "README routing contract drift")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        emit("FAIL", "routing-contract", str(exc))
    raw_support = lock.get("support_files", [])
    raw_local = lock.get("local_files", [])
    locked_auxiliary = [
        *(raw_support if isinstance(raw_support, list) else []),
        *(raw_local if isinstance(raw_local, list) else []),
    ]
    for support in locked_auxiliary:
        if not isinstance(support, dict) or not isinstance(support.get("path"), str):
            emit("FAIL", "skill-support", "invalid lock record")
            continue
        path = (ROOT / support["path"]).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError:
            emit("FAIL", "skill-support", f"path escapes workspace: {support['path']}")
            continue
        raw_expected = support.get("sha256", "")
        if not isinstance(raw_expected, str):
            emit("FAIL", "skill-support", f"invalid checksum: {support['path']}")
            continue
        expected = raw_expected.lower()
        actual = locked_support_sha256(path, support["path"]) if path.is_file() else ""
        valid = bool(actual) and (not expected or actual == expected)
        detail = relative_display(path) if valid else f"missing or checksum mismatch: {relative_display(path)}"
        emit("PASS" if valid else "FAIL", "skill-support", detail)

    if getattr(args, "project_only", False):
        print("\nProject-only doctor skipped host and optional tool probes.")
        return 1 if failures else 0

    probes = {
        "git": ["git", "--version"],
        "git-lfs": ["git", "lfs", "version"],
        "python": [sys.executable, "--version"],
        "node": ["node", "--version"],
        "npm": ["npm.cmd" if os.name == "nt" else "npm", "--version"],
    }
    for name, command in probes.items():
        if not shutil.which(command[0]) and command[0] != sys.executable:
            emit("WARN", name, "not found")
            continue
        code, output = run_probe(command)
        emit("PASS" if code == 0 else "WARN", name, output.splitlines()[0] if output else f"exit={code}")

    optional = ("pwsh", "docker", "7z", "jq", "gdb", "file", "socat", "ncat")
    for name in optional:
        path = shutil.which(name)
        emit("PASS" if path else "WARN", name, path or "not on Windows PATH")

    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        emit("FAIL" if getattr(args, "wsl_tools", False) else "WARN", "WSL", "wsl.exe not found")
    else:
        code, output = run_probe([wsl, "--list", "--quiet"])
        if code == 0:
            emit("PASS", "WSL", output or "installed; no distribution reported")
            if getattr(args, "wsl_tools", False):
                distribution = str(project_config().get("linux_environment") or "kali-linux")
                wsl_root = windows_path_to_wsl(ROOT)
                if not wsl_root:
                    path_code, mapped_output = run_probe(
                        [wsl, "-d", distribution, "--", "wslpath", "-a", str(ROOT)],
                        timeout=20,
                    )
                    wsl_root = mapped_output if path_code == 0 else ""
                if not wsl_root:
                    emit("FAIL", "WSL CTF tools", f"unable to map workspace into {distribution}")
                else:
                    verify_script = f"{wsl_root.rstrip('/')}/scripts/install_ctf_tools.sh"
                    tool_code, tool_output = run_probe(
                        [wsl, "-d", distribution, "--", "bash", verify_script, "--verify"],
                        timeout=180,
                    )
                    summary = "; ".join(line.strip() for line in tool_output.splitlines()[-3:] if line.strip())
                    emit(
                        "PASS" if tool_code == 0 and "Missing: 0" in tool_output else "FAIL",
                        "WSL CTF tools",
                        summary or f"exit={tool_code}",
                    )
        else:
            state = "FAIL" if getattr(args, "wsl_tools", False) else "BLOCKED"
            emit(state, "WSL", f"installed, but distribution enumeration failed (exit={code})")

    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\FileSystem",
            ) as key:
                enabled, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
            emit("PASS" if enabled else "WARN", "Windows long paths", "enabled" if enabled else "disabled; keep challenge paths short")
        except OSError as exc:
            emit("WARN", "Windows long paths", f"unable to inspect: {exc}")

    print("\nFAIL means the project itself is incomplete; WARN/BLOCKED identifies optional tooling for the next setup phase.")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    config = project_config()
    lock = read_json(SKILLS_LOCK, {}) or {}
    if not isinstance(lock, dict):
        raise ValueError(f"skills lock JSON root must be an object: {relative_display(SKILLS_LOCK)}")
    default_manifest = resolve_workspace_path(str(lock.get("manifest") or SKILLS_MANIFEST))
    parser = argparse.ArgumentParser(prog="ctf", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser("new", help="create a challenge from the standard template")
    new.add_argument("--event", default=str(config.get("default_event", "practice")))
    new.add_argument("--category", required=True)
    new.add_argument("--name", required=True)
    new.add_argument("--source-url", help="challenge page or download source")
    new.add_argument("--target-url", help="authorized HTTP service target")
    new.add_argument("--url", help="legacy alias that sets both source and target URL")
    new.add_argument("--host")
    new.add_argument("--port", type=int)
    new.add_argument(
        "--flag-regex",
        default=str(config.get("default_flag_regex", r"(?i)[a-z0-9_]+\{[^\r\n}]+\}")),
    )
    new.set_defaults(handler=cmd_new)

    triage = subparsers.add_parser("triage", help="inventory, identify, and hash original artifacts")
    triage.add_argument("challenge")
    triage.add_argument("--hash-limit-mb", type=int, default=0, help="0 hashes files of any size (default)")
    triage.add_argument("--flag-scan-mb", type=int, default=32)
    triage.set_defaults(handler=cmd_triage)

    import_artifacts = subparsers.add_parser(
        "import",
        help="safely copy original files or directory trees into challenge input/",
    )
    import_artifacts.add_argument("challenge")
    import_artifacts.add_argument("sources", nargs="+")
    import_artifacts.set_defaults(handler=cmd_import)

    verify_input = subparsers.add_parser(
        "verify-input",
        help="hash every input artifact and compare it with the tracked manifest",
    )
    verify_input.add_argument("challenge")
    verify_input.set_defaults(handler=cmd_verify_input)

    verify = subparsers.add_parser(
        "verify",
        help="run solve/solve.py with limits and write a redacted reproducibility proof",
    )
    verify.add_argument("challenge")
    verify.add_argument("--timeout", type=float, default=60.0)
    verify.add_argument("--max-output-mb", type=float, default=4.0)
    verify.add_argument("--record", action="store_true", help="store the verified candidate only in .local and mark solved")
    verify.add_argument("solver_args", nargs="*", help="arguments after -- are passed to solve.py")
    verify.set_defaults(handler=cmd_verify)

    agent_work = subparsers.add_parser(
        "agent-work",
        help="create an isolated work/agents/<name>/ directory and findings log",
    )
    agent_work.add_argument("challenge")
    agent_work.add_argument("name")
    agent_work.add_argument("--reuse", action="store_true", help="reuse an existing agent directory without overwriting findings")
    agent_work.set_defaults(handler=cmd_agent_work)

    route = subparsers.add_parser("route", help="initialize and show deterministic model routing for a challenge")
    route.add_argument("challenge")
    route.set_defaults(handler=cmd_route)

    routing_status = subparsers.add_parser("routing-status", help="show routing state and mandatory escalation gate")
    routing_status.add_argument("challenge")
    routing_status.set_defaults(handler=cmd_routing_status)

    checkpoint = subparsers.add_parser("checkpoint", help="record an attempt and enforce the next model-routing gate")
    checkpoint.add_argument("challenge")
    checkpoint.add_argument("--strategy", required=True)
    checkpoint.add_argument("--primitive", help="root-cause/attack primitive; variations share one primitive")
    checkpoint.add_argument("--result", choices=("fail", "progress", "blocked"), required=True)
    checkpoint.add_argument("--independent", action="store_true", help="count a failed, materially distinct primitive once")
    checkpoint.add_argument("--evidence", help="short material evidence summary")
    checkpoint.add_argument("--model", choices=("luna", "terra", "sol", "astra"), default="terra")
    checkpoint.add_argument("--native-critical", action="store_true")
    checkpoint.add_argument("--conflicting-hypotheses", action="store_true")
    checkpoint.add_argument("--sol-outcome", choices=("decisive", "unresolved"))
    checkpoint.set_defaults(handler=cmd_checkpoint)

    complete = subparsers.add_parser("complete", help="record one required terminal completion state with a reproducible reason")
    complete.add_argument("challenge")
    complete.add_argument("--state", choices=("USER_GOAL_COMPLETED", "ESCALATED", "BLOCKED_WITH_REPRODUCIBLE_REASON"), required=True)
    complete.add_argument("--reason", required=True)
    complete.set_defaults(handler=cmd_complete)

    status = subparsers.add_parser("status", help="list all challenge states")
    status.set_defaults(handler=cmd_status)

    flag = subparsers.add_parser("flag", help="store a verified flag locally and mark solved")
    flag.add_argument("challenge")
    flag.add_argument("value", nargs="?", help="omit to enter without shell history")
    flag.add_argument("--allow-nonmatching", action="store_true")
    flag.add_argument("--allow-unverified", action="store_true", help="manual escape hatch when no current solve proof exists")
    flag.set_defaults(handler=cmd_flag)

    doctor = subparsers.add_parser("doctor", help="validate project skills and host tooling")
    doctor_scope = doctor.add_mutually_exclusive_group()
    doctor_scope.add_argument("--project-only", action="store_true", help="skip host, WSL, and optional tool probes")
    doctor_scope.add_argument("--wsl-tools", action="store_true", help="run the pinned 58-item tool check inside configured WSL")
    doctor.set_defaults(handler=cmd_doctor)

    skills_check = subparsers.add_parser("skills-check", help="compare the pinned skill commit with its remote ref")
    skills_check.add_argument("--timeout", type=float, default=20.0)
    skills_check.add_argument("--strict", action="store_true", help="return 1 when an update is available")
    skills_check.set_defaults(handler=cmd_skills_check)

    skills_stage = subparsers.add_parser(
        "skills-stage",
        help="clone and validate a possible skill update under .cache without promotion",
    )
    skills_stage.add_argument("--timeout", type=float, default=180.0)
    skills_stage.add_argument("--staging-dir", help="new child directory under workspace .cache")
    skills_stage.set_defaults(handler=cmd_skills_stage)

    manifest = subparsers.add_parser("skills-manifest", help="validate and hash the vendored skill snapshot")
    manifest.add_argument("--skills-root", default=str(SKILLS_ROOT))
    manifest.add_argument("--commit")
    manifest.add_argument("--output", default=str(default_manifest))
    manifest.set_defaults(handler=cmd_skills_manifest)
    return parser


def main() -> int:
    try:
        parser = build_parser()
        args = parser.parse_args()
        return args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError, re.error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
