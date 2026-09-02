from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import importlib.util
import io
import json
import shutil
import unittest
import uuid
from pathlib import Path, PurePosixPath
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ctf.py"
PROJECT_ROOT = SCRIPT.parents[1]
SPEC = importlib.util.spec_from_file_location("ctf_artifact_tests", SCRIPT)
assert SPEC and SPEC.loader
ctf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ctf)


class ArtifactWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        cache = PROJECT_ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        self.root = cache / f"artifact-test-{uuid.uuid4().hex}"
        self.root.mkdir()
        ctf.ROOT = self.root
        ctf.CTF_CONFIG = self.root / ".ctf" / "config.json"
        ctf.SKILLS_LOCK = self.root / ".ctf" / "skills.lock.json"
        ctf.SKILLS_MANIFEST = self.root / ".ctf" / "skills.manifest.json"
        ctf.SKILLS_ROOT = self.root / ".agents" / "skills"
        ctf.CHALLENGE_ROOT = self.root / "c"
        ctf.LOCAL_FLAGS = self.root / ".local" / "flags.json"
        ctf.TEMPLATE_ROOT = PROJECT_ROOT / "templates" / "challenge"
        ctf.write_json(
            ctf.CTF_CONFIG,
            {
                "challenge_root": "c",
                "default_event": "practice",
                "default_flag_regex": r"(?i)[a-z0-9_]+\{[^\r\n}]+\}",
                "categories": ctf.DEFAULT_CATEGORIES,
            },
        )
        self.challenge = self.root / "c" / "event" / "misc" / "sample"
        (self.challenge / "input").mkdir(parents=True)
        (self.challenge / "input" / ".gitkeep").touch()
        (self.challenge / "evidence").mkdir()
        (self.challenge / "work").mkdir()
        ctf.write_json(
            self.challenge / "challenge.json",
            {"schema_version": 1, "id": "event/misc/sample", "category": "misc"},
        )
        self.sources = self.root / "sources"
        self.sources.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def import_sources(self, *sources: Path) -> int:
        return ctf.cmd_import(
            argparse.Namespace(
                challenge=str(self.challenge),
                sources=[str(source) for source in sources],
            )
        )

    def test_imports_file_and_directory_with_deterministic_manifest(self) -> None:
        single = self.sources / "single.bin"
        single.write_bytes(b"single artifact\x00")
        bundle = self.sources / "bundle"
        (bundle / "nested").mkdir(parents=True)
        (bundle / "z.txt").write_bytes(b"last")
        (bundle / "nested" / "a.bin").write_bytes(b"first")

        self.assertEqual(self.import_sources(bundle, single), 0)
        self.assertEqual((self.challenge / "input" / "single.bin").read_bytes(), single.read_bytes())
        self.assertEqual(
            (self.challenge / "input" / "bundle" / "nested" / "a.bin").read_bytes(),
            b"first",
        )

        manifest_path = self.challenge / "evidence" / "input-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["algorithm"], "sha256")
        self.assertEqual(manifest["file_count"], 3)
        paths = [record["path"] for record in manifest["files"]]
        self.assertEqual(paths, ["input/bundle/nested/a.bin", "input/bundle/z.txt", "input/single.bin"])
        serialized = manifest_path.read_text(encoding="utf-8")
        self.assertNotIn(str(self.sources), serialized)
        self.assertNotIn("source", serialized.lower())
        self.assertNotIn("generated_at", serialized)
        self.assertEqual(ctf.cmd_verify_input(argparse.Namespace(challenge=str(self.challenge))), 0)
        self.assertFalse(any((self.challenge / "work").glob("ctf-import-*")))

    def test_collision_rejected_without_changing_original_or_manifest(self) -> None:
        first_dir = self.sources / "first"
        second_dir = self.sources / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        first = first_dir / "payload.bin"
        second = second_dir / "PAYLOAD.BIN"
        first.write_bytes(b"original")
        second.write_bytes(b"replacement")

        self.assertEqual(self.import_sources(first), 0)
        manifest_path = self.challenge / "evidence" / "input-manifest.json"
        manifest_before = manifest_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.import_sources(second)
        self.assertEqual((self.challenge / "input" / "payload.bin").read_bytes(), b"original")
        self.assertEqual(manifest_path.read_bytes(), manifest_before)

        left = self.sources / "left"
        right = self.sources / "right"
        left.mkdir()
        right.mkdir()
        left_file = left / "same.dat"
        right_file = right / "SAME.DAT"
        left_file.write_bytes(b"left")
        right_file.write_bytes(b"right")
        with self.assertRaisesRegex(ValueError, "collision"):
            self.import_sources(left_file, right_file)
        self.assertFalse((self.challenge / "input" / "same.dat").exists())

    def test_manifest_path_escape_and_non_normalized_paths_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsafe artifact path component"):
            ctf._validate_import_relative(
                PurePosixPath("input/../outside.bin"),
                require_input_prefix=True,
            )

        manifest_path = self.challenge / "evidence" / "input-manifest.json"
        ctf.write_json(
            manifest_path,
            {
                "schema_version": 1,
                "algorithm": "sha256",
                "file_count": 1,
                "files": [{"path": "input/../outside.bin", "size": 0, "sha256": "0" * 64}],
            },
        )
        with self.assertRaises(ValueError):
            ctf.cmd_verify_input(argparse.Namespace(challenge=str(self.challenge)))

    def test_manifest_failure_rolls_back_promoted_artifacts(self) -> None:
        source = self.sources / "rollback.bin"
        source.write_bytes(b"must not remain")
        with mock.patch.object(ctf, "_write_input_manifest", side_effect=OSError("simulated failure")):
            with self.assertRaisesRegex(OSError, "simulated failure"):
                self.import_sources(source)
        self.assertFalse((self.challenge / "input" / "rollback.bin").exists())
        self.assertFalse((self.challenge / "evidence" / "input-manifest.json").exists())
        self.assertFalse(any((self.challenge / "work").glob("ctf-import-*")))

    def test_keyboard_interrupt_rolls_back_artifacts_and_manifest(self) -> None:
        source = self.sources / "interrupt.bin"
        source.write_bytes(b"must roll back")
        with mock.patch.object(ctf, "_write_input_manifest", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.import_sources(source)
        self.assertFalse((self.challenge / "input" / "interrupt.bin").exists())
        self.assertFalse((self.challenge / "evidence" / "input-manifest.json").exists())
        self.assertFalse(any((self.challenge / "work").glob("ctf-import-*")))

    def test_nonempty_gitkeep_is_reported_as_extra(self) -> None:
        source = self.sources / "tracked.bin"
        source.write_bytes(b"tracked")
        self.assertEqual(self.import_sources(source), 0)
        (self.challenge / "input" / ".gitkeep").write_bytes(b"hidden data")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = ctf.cmd_verify_input(argparse.Namespace(challenge=str(self.challenge)))
        self.assertEqual(result, 1)
        self.assertIn("[EXTRA  ] input/.gitkeep", output.getvalue())

    def test_parallel_imports_are_serialized_without_lost_manifest_entries(self) -> None:
        first = self.sources / "first.bin"
        second = self.sources / "second.bin"
        first.write_bytes(b"first")
        second.write_bytes(b"second")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.import_sources, source) for source in (first, second)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(results, [0, 0])
        manifest = ctf.read_json(self.challenge / "evidence" / "input-manifest.json")
        self.assertEqual(
            [record["path"] for record in manifest["files"]],
            ["input/first.bin", "input/second.bin"],
        )
        self.assertEqual(ctf.cmd_verify_input(argparse.Namespace(challenge=str(self.challenge))), 0)

    def test_import_rejects_reparse_like_work_and_evidence_directories(self) -> None:
        source = self.sources / "safe.bin"
        source.write_bytes(b"safe")
        original = ctf._is_link_like

        for unsafe in (self.challenge / "work", self.challenge / "evidence"):
            with self.subTest(unsafe=unsafe.name):
                def link_check(path: Path, *, unsafe_path: Path = unsafe) -> bool:
                    return Path(path) == unsafe_path or original(Path(path))

                with mock.patch.object(ctf, "_is_link_like", side_effect=link_check):
                    with self.assertRaisesRegex(ValueError, "link or junction"):
                        self.import_sources(source)
                self.assertFalse((self.challenge / "input" / "safe.bin").exists())

    def test_verify_reports_missing_changed_and_extra_and_hashes_all_files(self) -> None:
        changed_source = self.sources / "changed.bin"
        missing_source = self.sources / "missing.bin"
        stable_source = self.sources / "stable.bin"
        changed_source.write_bytes(b"before")
        missing_source.write_bytes(b"remove me")
        stable_source.write_bytes(b"stable")
        self.assertEqual(self.import_sources(changed_source, missing_source, stable_source), 0)

        (self.challenge / "input" / "changed.bin").write_bytes(b"after")
        (self.challenge / "input" / "missing.bin").unlink()
        (self.challenge / "input" / "extra.bin").write_bytes(b"extra")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = ctf.cmd_verify_input(argparse.Namespace(challenge=str(self.challenge)))
        self.assertEqual(result, 1)
        report = output.getvalue()
        self.assertIn("[MISSING] input/missing.bin", report)
        self.assertIn("[CHANGED] input/changed.bin", report)
        self.assertIn("[EXTRA  ] input/extra.bin", report)

    def test_triage_hashes_all_sizes_by_default(self) -> None:
        args = ctf.build_parser().parse_args(["triage", str(self.challenge)])
        self.assertEqual(args.hash_limit_mb, 0)


if __name__ == "__main__":
    unittest.main()
