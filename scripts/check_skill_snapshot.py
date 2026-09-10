#!/usr/bin/env python3
"""Strict, dependency-free validation for the project-scoped CTF skill snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = Path(".ctf/skills.lock.json")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SKILL_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
FRONTMATTER_MAX_LINES = 128
FRONTMATTER_MAX_BYTES = 16 * 1024


@dataclass(frozen=True)
class SnapshotResult:
    errors: tuple[str, ...]
    skill_count: int
    file_count: int

    @property
    def ok(self) -> bool:
        return not self.errors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_locked_file(path: Path, relative: str, expected: str) -> str:
    """Hash lock payload; tolerate Git's CRLF checkout for the vendored license.

    Prefer the exact on-disk hash: fixtures and repositories with LF checkouts
    must retain their original behavior.  Only fall back to LF normalization
    when the lone vendored license is checked out with CRLF on Windows.
    """
    raw = sha256_file(path)
    if raw == expected or not relative.replace("\\", "/").endswith("LICENSE.ctf-skills"):
        return raw
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def skill_tree_hash(entries: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in sorted(entries.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _read_json(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label}: cannot read valid JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label}: top-level value must be an object")
        return {}
    return value


def _canonical_relative(value: Any, label: str, errors: list[str]) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\\" in value:
        errors.append(f"{label}: path must be a non-empty canonical POSIX path")
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        errors.append(f"{label}: unsafe or non-canonical path {value!r}")
        return None
    return path


def _inside(root: Path, path: Path, label: str, errors: list[str]) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        errors.append(f"{label}: path escapes workspace: {path}")
        return False
    return True


def _locked_files(
    lock: dict[str, Any],
    key: str,
    workspace: Path,
    skills_root: Path,
    scope: PurePosixPath,
    errors: list[str],
) -> dict[str, str]:
    raw_entries = lock.get(key, [])
    if not isinstance(raw_entries, list):
        errors.append(f"lock.{key}: must be a list")
        return {}

    entries: dict[str, str] = {}
    for index, raw in enumerate(raw_entries):
        label = f"lock.{key}[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{label}: must be an object")
            continue
        path = _canonical_relative(raw.get("path"), f"{label}.path", errors)
        expected_hash = raw.get("sha256")
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            errors.append(f"{label}.sha256: must be lowercase SHA-256")
            continue
        if path is None:
            continue
        try:
            relative = path.relative_to(scope).as_posix()
        except ValueError:
            errors.append(f"{label}.path: must be inside {scope.as_posix()}/")
            continue
        absolute = workspace.joinpath(*path.parts)
        if not _inside(skills_root, absolute, f"{label}.path", errors):
            continue
        if relative in entries:
            errors.append(f"lock.{key}: duplicate path {path.as_posix()!r}")
            continue
        entries[relative] = expected_hash
    return entries


def _validate_frontmatter(path: Path, expected_name: str) -> tuple[list[str], str | None]:
    errors: list[str] = []
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"{expected_name}/SKILL.md: cannot read UTF-8: {exc}"], None

    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return [f"{expected_name}/SKILL.md: frontmatter must start with ---"], None

    closing: int | None = None
    for index, line in enumerate(lines[1 : FRONTMATTER_MAX_LINES + 1], start=1):
        if line == "---":
            closing = index
            break
    if closing is None:
        return [
            f"{expected_name}/SKILL.md: frontmatter must close within "
            f"{FRONTMATTER_MAX_LINES} lines"
        ], None

    frontmatter_bytes = "\n".join(lines[: closing + 1]).encode("utf-8")
    if len(frontmatter_bytes) > FRONTMATTER_MAX_BYTES:
        errors.append(
            f"{expected_name}/SKILL.md: frontmatter exceeds {FRONTMATTER_MAX_BYTES} bytes"
        )

    fields: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing], start=2):
        if not line.strip() or line.lstrip().startswith("#") or line[:1].isspace():
            continue
        match = TOP_LEVEL_KEY_RE.fullmatch(line)
        if not match:
            errors.append(
                f"{expected_name}/SKILL.md:{line_number}: invalid top-level frontmatter"
            )
            continue
        key, raw_value = match.groups()
        if key in fields:
            errors.append(
                f"{expected_name}/SKILL.md:{line_number}: duplicate frontmatter key {key!r}"
            )
            continue
        fields[key] = (raw_value or "").strip()

    declared_name = fields.get("name", "").strip("\"'")
    description = fields.get("description", "").strip("\"'")
    if not declared_name:
        errors.append(f"{expected_name}/SKILL.md: required frontmatter name is missing")
    elif declared_name != expected_name:
        errors.append(
            f"{expected_name}/SKILL.md: declares name={declared_name!r}, expected {expected_name!r}"
        )
    if not description:
        errors.append(f"{expected_name}/SKILL.md: required frontmatter description is missing")
    return errors, declared_name or None


def validate_snapshot(workspace: Path = ROOT, lock_path: Path | None = None) -> SnapshotResult:
    workspace = workspace.resolve()
    errors: list[str] = []
    lock_path = lock_path or workspace / DEFAULT_LOCK
    if not lock_path.is_absolute():
        lock_path = workspace / lock_path
    if not _inside(workspace, lock_path, "lock", errors):
        return SnapshotResult(tuple(errors), 0, 0)
    lock = _read_json(lock_path, "lock", errors)

    scope = _canonical_relative(lock.get("scope"), "lock.scope", errors)
    if scope is None:
        return SnapshotResult(tuple(errors), 0, 0)
    skills_root = workspace.joinpath(*scope.parts)
    if not _inside(workspace, skills_root, "lock.scope", errors):
        return SnapshotResult(tuple(errors), 0, 0)
    if not skills_root.is_dir():
        errors.append(f"skill root is missing: {scope.as_posix()}")

    raw_skills = lock.get("skills")
    skills: list[str] = []
    if not isinstance(raw_skills, list) or not raw_skills:
        errors.append("lock.skills: must be a non-empty list")
    else:
        for index, value in enumerate(raw_skills):
            if not isinstance(value, str) or not SKILL_NAME_RE.fullmatch(value):
                errors.append(f"lock.skills[{index}]: invalid skill name {value!r}")
            else:
                skills.append(value)
        duplicates = sorted({name for name in skills if skills.count(name) > 1})
        if duplicates:
            errors.append(f"lock.skills: duplicate names: {', '.join(duplicates)}")
    skill_set = set(skills)

    manifest_value = lock.get("manifest")
    manifest_relative = _canonical_relative(manifest_value, "lock.manifest", errors)
    manifest: dict[str, Any] = {}
    if manifest_relative is not None:
        manifest_path = workspace.joinpath(*manifest_relative.parts)
        if _inside(workspace, manifest_path, "lock.manifest", errors):
            manifest = _read_json(manifest_path, "manifest", errors)

    raw_manifest_files = manifest.get("files")
    manifest_files: dict[str, str] = {}
    if not isinstance(raw_manifest_files, dict) or not raw_manifest_files:
        errors.append("manifest.files: must be a non-empty object")
    else:
        for raw_path, raw_hash in raw_manifest_files.items():
            path = _canonical_relative(raw_path, "manifest.files path", errors)
            if path is None:
                continue
            if path.parts[0] not in skill_set:
                errors.append(
                    f"manifest.files: {path.as_posix()!r} is outside a locked skill directory"
                )
                continue
            if not isinstance(raw_hash, str) or not SHA256_RE.fullmatch(raw_hash):
                errors.append(
                    f"manifest.files[{path.as_posix()!r}]: must be lowercase SHA-256"
                )
                continue
            manifest_files[path.as_posix()] = raw_hash

    support_files = _locked_files(
        lock, "support_files", workspace, skills_root, scope, errors
    )
    local_files = _locked_files(lock, "local_files", workspace, skills_root, scope, errors)

    expected_files: dict[str, str] = {}
    for label, entries in (
        ("manifest.files", manifest_files),
        ("lock.support_files", support_files),
        ("lock.local_files", local_files),
    ):
        for relative, expected_hash in entries.items():
            if relative in expected_files:
                errors.append(f"{label}: path is declared more than once: {relative!r}")
            else:
                expected_files[relative] = expected_hash

    actual_files: dict[str, Path] = {}
    actual_dirs: set[str] = set()
    if skills_root.is_dir():
        for path in skills_root.rglob("*"):
            relative = path.relative_to(skills_root).as_posix()
            if path.is_symlink():
                errors.append(f"skill tree contains a symlink: {relative}")
            elif path.is_dir():
                actual_dirs.add(relative)
            elif path.is_file():
                actual_files[relative] = path

    expected_dirs = set(skill_set)
    for relative in expected_files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    for relative in sorted(actual_dirs - expected_dirs):
        qualifier = "top-level " if "/" not in relative else ""
        errors.append(f"unexpected {qualifier}skill directory: {relative}")
    for relative in sorted(expected_dirs - actual_dirs):
        qualifier = "top-level " if "/" not in relative else ""
        errors.append(f"missing {qualifier}skill directory: {relative}")

    actual_paths = set(actual_files)
    expected_paths = set(expected_files)
    for relative in sorted(actual_paths - expected_paths):
        errors.append(f"unexpected skill file: {relative}")
    for relative in sorted(expected_paths - actual_paths):
        errors.append(f"missing skill file: {relative}")
    for relative in sorted(expected_paths & actual_paths):
        actual_hash = sha256_locked_file(
            actual_files[relative], relative, expected_files[relative]
        )
        if actual_hash != expected_files[relative]:
            errors.append(f"skill checksum mismatch: {relative}")

    expected_tree = skill_tree_hash(manifest_files) if manifest_files else ""
    manifest_tree = manifest.get("tree_sha256")
    lock_tree = lock.get("tree_sha256")
    if manifest_tree != expected_tree:
        errors.append("manifest.tree_sha256 does not match manifest.files")
    if lock_tree != expected_tree:
        errors.append("lock.tree_sha256 does not match manifest.files")
    if manifest.get("file_count") != len(manifest_files):
        errors.append("manifest.file_count does not match manifest.files")

    lock_commit = lock.get("resolved_commit")
    manifest_commit = manifest.get("source_commit")
    if not isinstance(lock_commit, str) or not COMMIT_RE.fullmatch(lock_commit):
        errors.append("lock.resolved_commit must be a lowercase 40-character Git commit")
    if manifest_commit != lock_commit:
        errors.append("manifest.source_commit does not match lock.resolved_commit")

    declared_names: dict[str, str] = {}
    for skill in sorted(skill_set):
        entrypoint = skills_root / skill / "SKILL.md"
        frontmatter_errors, declared_name = _validate_frontmatter(entrypoint, skill)
        errors.extend(frontmatter_errors)
        if declared_name:
            previous = declared_names.get(declared_name)
            if previous is not None and previous != skill:
                errors.append(
                    f"duplicate declared skill name {declared_name!r}: {previous}, {skill}"
                )
            else:
                declared_names[declared_name] = skill

    return SnapshotResult(tuple(errors), len(skill_set), len(actual_files))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the exact project-scoped CTF skill snapshot"
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="workspace root")
    parser.add_argument(
        "--lock",
        type=Path,
        default=None,
        help="lock file (relative paths resolve from --root)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_snapshot(args.root, args.lock)
    if not result.ok:
        print(f"FAIL skill snapshot ({len(result.errors)} issue(s))", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(
        f"PASS skill snapshot: {result.skill_count} skills, "
        f"{result.file_count} locked files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
