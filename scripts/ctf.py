#!/usr/bin/env python3
"""Small, dependency-free CLI for the lee-ctf workspace."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
CTF_CONFIG = ROOT / ".ctf" / "config.json"
SKILLS_LOCK = ROOT / ".ctf" / "skills.lock.json"
SKILLS_MANIFEST = ROOT / ".ctf" / "skills.manifest.json"
SKILLS_ROOT = ROOT / ".agents" / "skills"
CHALLENGE_ROOT = ROOT / "c"
TEMPLATE_ROOT = ROOT / "templates" / "challenge"
LOCAL_FLAGS = ROOT / ".local" / "flags.json"

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


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value).strip(" .-")
    if not value:
        raise ValueError("name becomes empty after path sanitization")
    if value.upper() in RESERVED_WINDOWS_NAMES:
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
    target_parts = [part for part in (args.url, args.host and f"{args.host}:{port or ''}".rstrip(":")) if part]
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
        "source_url": args.url or "",
        "target": {"url": args.url or "", "host": args.host or "", "port": port},
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
        "SOURCE_URL": args.url or "(not provided)",
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

    print(relative_display(destination))
    print(f"skill: {skill}")
    print("next: copy original artifacts into input/ and run triage")
    return 0


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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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

    report = {
        "generated_at": utc_now(),
        "challenge": relative_display(directory),
        "files": records,
        "flag_candidates": sorted(candidates),
    }
    report_path = directory / "work" / "triage.json"
    write_json(report_path, report)
    print(f"{'TYPE':<22} {'SIZE':>12}  {'SHA256':<12} PATH")
    for record in records:
        short_hash = record["sha256"][:12] if record["sha256"] else "skipped"
        print(f"{record['type']:<22} {record['size']:>12}  {short_hash:<12} {record['path']}")
    if candidates:
        print("flag candidates:")
        for candidate in sorted(candidates):
            print(f"  {candidate}")
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


def cmd_flag(args: argparse.Namespace) -> int:
    directory = challenge_dir(args.challenge)
    metadata_path = directory / "challenge.json"
    metadata = read_json(metadata_path, {})
    candidate = args.value or getpass.getpass("Verified flag: ")
    if not candidate:
        raise ValueError("flag cannot be empty")
    pattern = re.compile(metadata.get("flag_regex") or r"(?i)[a-z0-9_]+\{[^\r\n}]+\}")
    if not pattern.fullmatch(candidate) and not args.allow_nonmatching:
        raise ValueError("candidate does not match flag_regex; use --allow-nonmatching only after manual verification")

    flags = read_json(LOCAL_FLAGS, {}) or {}
    key = directory.relative_to(CHALLENGE_ROOT).as_posix()
    flags[key] = {"flag": candidate, "recorded_at": utc_now()}
    write_json(LOCAL_FLAGS, flags)
    metadata["status"] = "solved"
    metadata["solved_at"] = utc_now()
    write_json(metadata_path, metadata)
    print(f"recorded locally and marked solved: {relative_display(directory)}")
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
    lock = read_json(SKILLS_LOCK, {}) or {}
    skills = [str(skill) for skill in lock.get("skills", [])]
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


def cmd_doctor(_args: argparse.Namespace) -> int:
    failures = 0

    def emit(state: str, name: str, detail: str) -> None:
        nonlocal failures
        if state == "FAIL":
            failures += 1
        print(f"[{state:<7}] {name:<20} {detail}")

    lock = read_json(SKILLS_LOCK, {}) or {}
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
    for support in lock.get("support_files", []):
        path = ROOT / support["path"]
        expected = support.get("sha256", "").lower()
        actual = sha256_file(path) if path.is_file() else ""
        valid = bool(actual) and (not expected or actual == expected)
        detail = relative_display(path) if valid else f"missing or checksum mismatch: {relative_display(path)}"
        emit("PASS" if valid else "FAIL", "skill-support", detail)

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
        emit("WARN", "WSL", "wsl.exe not found")
    else:
        code, output = run_probe([wsl, "--list", "--quiet"])
        if code == 0:
            emit("PASS", "WSL", output or "installed; no distribution reported")
        else:
            emit("BLOCKED", "WSL", f"installed, but distribution enumeration failed (exit={code})")

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
    default_manifest = resolve_workspace_path(str(lock.get("manifest") or SKILLS_MANIFEST))
    parser = argparse.ArgumentParser(prog="ctf", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser("new", help="create a challenge from the standard template")
    new.add_argument("--event", default=str(config.get("default_event", "practice")))
    new.add_argument("--category", required=True)
    new.add_argument("--name", required=True)
    new.add_argument("--url")
    new.add_argument("--host")
    new.add_argument("--port", type=int)
    new.add_argument(
        "--flag-regex",
        default=str(config.get("default_flag_regex", r"(?i)[a-z0-9_]+\{[^\r\n}]+\}")),
    )
    new.set_defaults(handler=cmd_new)

    triage = subparsers.add_parser("triage", help="inventory, identify, and hash original artifacts")
    triage.add_argument("challenge")
    triage.add_argument("--hash-limit-mb", type=int, default=512, help="0 hashes files of any size")
    triage.add_argument("--flag-scan-mb", type=int, default=32)
    triage.set_defaults(handler=cmd_triage)

    status = subparsers.add_parser("status", help="list all challenge states")
    status.set_defaults(handler=cmd_status)

    flag = subparsers.add_parser("flag", help="store a verified flag locally and mark solved")
    flag.add_argument("challenge")
    flag.add_argument("value", nargs="?", help="omit to enter without shell history")
    flag.add_argument("--allow-nonmatching", action="store_true")
    flag.set_defaults(handler=cmd_flag)

    doctor = subparsers.add_parser("doctor", help="validate project skills and host tooling")
    doctor.set_defaults(handler=cmd_doctor)

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
