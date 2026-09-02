from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "skill_source.py"
SPEC = importlib.util.spec_from_file_location("skill_source", SCRIPT)
assert SPEC and SPEC.loader
skill_source = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = skill_source
SPEC.loader.exec_module(skill_source)
PROJECT_ROOT = SCRIPT.parents[1]


class SkillSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        cache = PROJECT_ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        self.root = cache / f"skill-source-test-{uuid.uuid4().hex}"
        self.root.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def _lock(self, root: Path, commit: str = "a" * 40) -> Path:
        lock_path = root / ".ctf" / "skills.lock.json"
        lock_path.parent.mkdir(parents=True)
        lock_path.write_text(
            json.dumps(
                {
                    "source": "https://token@example.invalid/owner/repository",
                    "ref": "main",
                    "resolved_commit": commit,
                    "skills": ["ctf-demo"],
                }
            ),
            encoding="utf-8",
        )
        return lock_path

    def test_check_source_detects_update_and_redacts_credentials(self) -> None:
        lock_path = self._lock(self.root)
        remote = "b" * 40
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{remote}\trefs/heads/main\n", stderr=""
        )
        with mock.patch.object(skill_source, "_run_git", return_value=completed):
            result = skill_source.check_source(lock_path)

        self.assertTrue(result["update_available"])
        self.assertEqual(result["remote_commit"], remote)
        self.assertNotIn("token", result["source"])

    def test_check_error_redacts_source_credentials(self) -> None:
        lock_path = self._lock(self.root)
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=128,
            stdout="",
            stderr=(
                "fatal: unable to access "
                "'https://token@example.invalid/owner/repository': unavailable\n"
            ),
        )
        with mock.patch.object(skill_source, "_run_git", return_value=completed):
            with self.assertRaises(skill_source.SkillSourceError) as raised:
                skill_source.check_source(lock_path)

        self.assertNotIn("token", str(raised.exception))

    def test_validate_staged_payload_hashes_expected_skill(self) -> None:
        skill = self.root / "ctf-demo"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: ctf-demo\ndescription: demo\n---\n\n# Demo\n",
            encoding="utf-8",
        )
        (skill / "guide.md").write_text("guide\n", encoding="utf-8")
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "install_ctf_tools.sh").write_text(
            "#!/bin/sh\n", encoding="utf-8"
        )
        (self.root / "LICENSE").write_text("license\n", encoding="utf-8")

        result = skill_source.validate_staged_payload(
            self.root,
            ["ctf-demo"],
            [
                {"path": ".agents/skills/scripts/install_ctf_tools.sh"},
                {"path": ".agents/skills/LICENSE.ctf-skills"},
            ],
        )

        self.assertEqual(result["skill_count"], 1)
        self.assertEqual(result["file_count"], 2)
        self.assertRegex(result["tree_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(result["support_files"]), 2)
        self.assertEqual(result["support_files"][1]["source_path"], "LICENSE")

    def test_stage_refuses_destination_outside_workspace_cache(self) -> None:
        lock_path = self._lock(self.root)
        with self.assertRaises(skill_source.SkillSourceError):
            skill_source.stage_source(
                lock_path,
                self.root / ".agents" / "skills",
                workspace_root=self.root,
            )

    def test_staged_frontmatter_requires_unique_name_and_description(self) -> None:
        skill = self.root / "ctf-demo"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: ctf-demo\nname: duplicate\n---\n",
            encoding="utf-8",
        )

        with self.assertRaises(skill_source.SkillSourceError):
            skill_source.validate_staged_payload(self.root, ["ctf-demo"])

    def test_staged_payload_rejects_linked_files(self) -> None:
        skill = self.root / "ctf-demo"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: ctf-demo\ndescription: demo\n---\n",
            encoding="utf-8",
        )
        external = self.root.parent / f"external-{uuid.uuid4().hex}.txt"
        external.write_text("outside\n", encoding="utf-8")
        try:
            try:
                (skill / "guide.md").symlink_to(external)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            with self.assertRaisesRegex(skill_source.SkillSourceError, "link or junction"):
                skill_source.validate_staged_payload(self.root, ["ctf-demo"])
        finally:
            external.unlink(missing_ok=True)

    def test_staged_payload_rejects_unlocked_skill_directories(self) -> None:
        for name in ("ctf-demo", "ctf-unexpected"):
            skill = self.root / name
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: demo\n---\n",
                encoding="utf-8",
            )

        with self.assertRaisesRegex(skill_source.SkillSourceError, "unexpected skills"):
            skill_source.validate_staged_payload(self.root, ["ctf-demo"])


if __name__ == "__main__":
    unittest.main()
