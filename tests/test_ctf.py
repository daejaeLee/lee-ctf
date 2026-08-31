from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import unittest
import uuid
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ctf.py"
PROJECT_ROOT = SCRIPT.parents[1]
SPEC = importlib.util.spec_from_file_location("ctf_workspace", SCRIPT)
assert SPEC and SPEC.loader
ctf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ctf)


class WorkspaceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        cache = PROJECT_ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        self.root = cache / f"test-{uuid.uuid4().hex}"
        self.root.mkdir()
        ctf.ROOT = self.root
        ctf.CTF_CONFIG = self.root / ".ctf" / "config.json"
        ctf.SKILLS_LOCK = self.root / ".ctf" / "skills.lock.json"
        ctf.SKILLS_MANIFEST = self.root / ".ctf" / "skills.manifest.json"
        ctf.SKILLS_ROOT = self.root / ".agents" / "skills"
        ctf.CHALLENGE_ROOT = self.root / "c"
        ctf.LOCAL_FLAGS = self.root / ".local" / "flags.json"
        ctf.TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates" / "challenge"
        ctf.write_json(
            ctf.CTF_CONFIG,
            {
                "challenge_root": "c",
                "default_event": "practice",
                "default_flag_regex": r"(?i)[a-z0-9_]+\{[^\r\n}]+\}",
                "categories": ctf.DEFAULT_CATEGORIES,
            },
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_slugify_and_alias(self) -> None:
        self.assertEqual(ctf.slugify("Baby SQLi"), "baby-sqli")
        self.assertEqual(ctf.normalize_category("rev"), "reverse")

    def test_project_config_drives_parser_defaults(self) -> None:
        config = ctf.read_json(ctf.CTF_CONFIG)
        config["default_event"] = "speedrun-2026"
        config["default_flag_regex"] = r"FLAG\{[^}]+\}"
        ctf.write_json(ctf.CTF_CONFIG, config)

        args = ctf.build_parser().parse_args(["new", "--category", "web", "--name", "demo"])
        self.assertEqual(args.event, "speedrun-2026")
        self.assertEqual(args.flag_regex, r"FLAG\{[^}]+\}")

    def test_skill_manifest_changes_with_vendored_files(self) -> None:
        skill_root = ctf.SKILLS_ROOT / "ctf-demo"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            "---\nname: ctf-demo\ndescription: test\n---\n\n[Guide](guide.md)\n",
            encoding="utf-8",
        )
        guide = skill_root / "guide.md"
        guide.write_text("version one\n", encoding="utf-8")
        ctf.write_json(ctf.SKILLS_LOCK, {"resolved_commit": "a" * 40, "skills": ["ctf-demo"]})

        args = argparse.Namespace(
            skills_root=str(ctf.SKILLS_ROOT),
            commit=None,
            output=str(ctf.SKILLS_MANIFEST),
        )
        self.assertEqual(ctf.cmd_skills_manifest(args), 0)
        before = ctf.read_json(ctf.SKILLS_MANIFEST)
        self.assertEqual(before["file_count"], 2)

        guide.write_text("version two\n", encoding="utf-8")
        self.assertEqual(ctf.cmd_skills_manifest(args), 0)
        after = ctf.read_json(ctf.SKILLS_MANIFEST)
        self.assertNotEqual(before["tree_sha256"], after["tree_sha256"])

    def test_new_triage_and_flag(self) -> None:
        create = argparse.Namespace(
            event="Test CTF 2026",
            category="misc",
            name="Warm Up",
            url=None,
            host=None,
            port=None,
            flag_regex=r"(?i)[a-z0-9_]+\{[^\r\n}]+\}",
        )
        self.assertEqual(ctf.cmd_new(create), 0)
        challenge = self.root / "c" / "test-ctf-2026" / "misc" / "warm-up"
        sample = challenge / "input" / "sample.bin"
        sample.write_bytes(b"\x89PNG\r\n\x1a\nnoise flag{self_test}\n")

        triage = argparse.Namespace(challenge=str(challenge), hash_limit_mb=512, flag_scan_mb=32)
        self.assertEqual(ctf.cmd_triage(triage), 0)
        report = json.loads((challenge / "work" / "triage.json").read_text(encoding="utf-8"))
        self.assertEqual(report["files"][0]["type"], "PNG")
        self.assertIn("flag{self_test}", report["flag_candidates"])

        record = argparse.Namespace(
            challenge=str(challenge),
            value="flag{self_test}",
            allow_nonmatching=False,
        )
        self.assertEqual(ctf.cmd_flag(record), 0)
        metadata = json.loads((challenge / "challenge.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "solved")
        self.assertNotIn("flag{self_test}", (challenge / "challenge.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
