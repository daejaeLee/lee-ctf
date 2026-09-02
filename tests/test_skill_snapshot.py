from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_skill_snapshot.py"
PROJECT_ROOT = MODULE_PATH.parents[1]
SPEC = importlib.util.spec_from_file_location("check_skill_snapshot", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
snapshot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = snapshot
SPEC.loader.exec_module(snapshot)


class SkillSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PROJECT_ROOT / ".cache" / f"skill-test-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.skills_root = self.root / ".agents" / "skills"
        self.skill = self.skills_root / "ctf-demo"
        self.skill.mkdir(parents=True)
        (self.skill / "SKILL.md").write_text(
            "---\n"
            "name: ctf-demo\n"
            "description: Demonstration skill for snapshot tests.\n"
            "metadata:\n"
            "  user-invocable: \"false\"\n"
            "---\n\n"
            "# Demo\n",
            encoding="utf-8",
        )
        (self.skill / "guide.md").write_text("guide\n", encoding="utf-8")

        support = self.skills_root / "scripts"
        support.mkdir()
        (support / "install_ctf_tools.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (support / "README.md").write_text("local metadata\n", encoding="utf-8")
        (self.skills_root / "LICENSE.ctf-skills").write_text("license\n", encoding="utf-8")

        manifest_files = {
            "ctf-demo/SKILL.md": snapshot.sha256_file(self.skill / "SKILL.md"),
            "ctf-demo/guide.md": snapshot.sha256_file(self.skill / "guide.md"),
        }
        tree_hash = snapshot.skill_tree_hash(manifest_files)
        commit = "a" * 40
        manifest = {
            "schema_version": 1,
            "source_commit": commit,
            "file_count": len(manifest_files),
            "tree_sha256": tree_hash,
            "files": manifest_files,
        }
        lock = {
            "schema_version": 1,
            "resolved_commit": commit,
            "scope": ".agents/skills",
            "manifest": ".ctf/skills.manifest.json",
            "tree_sha256": tree_hash,
            "skills": ["ctf-demo"],
            "support_files": [
                self._lock_entry(".agents/skills/scripts/install_ctf_tools.sh"),
                self._lock_entry(".agents/skills/LICENSE.ctf-skills"),
            ],
            "local_files": [self._lock_entry(".agents/skills/scripts/README.md")],
        }
        metadata = self.root / ".ctf"
        metadata.mkdir()
        (metadata / "skills.manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (metadata / "skills.lock.json").write_text(json.dumps(lock), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def _lock_entry(self, relative: str) -> dict[str, str]:
        path = self.root.joinpath(*relative.split("/"))
        return {"path": relative, "sha256": snapshot.sha256_file(path)}

    def validate(self):
        return snapshot.validate_snapshot(self.root)

    def test_accepts_exact_locked_tree(self) -> None:
        result = self.validate()
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.skill_count, 1)
        self.assertEqual(result.file_count, 5)

    def test_rejects_unlocked_files_and_skill_directories(self) -> None:
        (self.skill / "extra.md").write_text("extra\n", encoding="utf-8")
        (self.skill / "empty").mkdir()
        extra_skill = self.skills_root / "ctf-extra"
        extra_skill.mkdir()
        (extra_skill / "SKILL.md").write_text("---\n---\n", encoding="utf-8")

        errors = self.validate().errors
        self.assertIn("unexpected skill file: ctf-demo/extra.md", errors)
        self.assertIn("unexpected skill directory: ctf-demo/empty", errors)
        self.assertIn("unexpected top-level skill directory: ctf-extra", errors)
        self.assertIn("unexpected skill file: ctf-extra/SKILL.md", errors)

    def test_rejects_locked_file_checksum_changes(self) -> None:
        (self.skills_root / "scripts" / "README.md").write_text(
            "changed local metadata\n", encoding="utf-8"
        )

        self.assertIn(
            "skill checksum mismatch: scripts/README.md", self.validate().errors
        )

    def test_requires_bounded_unique_frontmatter_fields(self) -> None:
        (self.skill / "SKILL.md").write_text(
            "---\n"
            "name: ctf-demo\n"
            "name: ctf-demo\n"
            + "# filler\n" * snapshot.FRONTMATTER_MAX_LINES
            + "---\n",
            encoding="utf-8",
        )

        errors = self.validate().errors
        self.assertTrue(any("frontmatter must close within" in error for error in errors))

    def test_rejects_duplicate_keys_and_missing_description(self) -> None:
        (self.skill / "SKILL.md").write_text(
            "---\nname: ctf-demo\nname: ctf-demo\n---\n", encoding="utf-8"
        )

        errors = self.validate().errors
        self.assertTrue(any("duplicate frontmatter key 'name'" in error for error in errors))
        self.assertTrue(any("frontmatter description is missing" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
