from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import time
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "solve_verification.py"
SPEC = importlib.util.spec_from_file_location("solve_verification", SCRIPT)
assert SPEC and SPEC.loader
verification = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verification
SPEC.loader.exec_module(verification)
PROJECT_ROOT = SCRIPT.parents[1]


class SolveVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        cache = PROJECT_ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        self.root = cache / f"verify-test-{uuid.uuid4().hex}"
        self.root.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def _challenge(self, root: Path, solver_source: str) -> Path:
        challenge = root / "c" / "event" / "misc" / "demo"
        (challenge / "solve").mkdir(parents=True)
        (challenge / "evidence").mkdir()
        (challenge / "challenge.json").write_text(
            json.dumps({"flag_regex": r"FLAG\{[^\r\n}]+\}"}),
            encoding="utf-8",
        )
        (challenge / "solve" / "solve.py").write_text(solver_source, encoding="utf-8")
        (challenge / "evidence" / "input-manifest.json").write_text(
            '{"schema_version":1,"algorithm":"sha256","file_count":0,"files":[]}\n',
            encoding="utf-8",
        )
        return challenge

    @staticmethod
    def _emit_flag(candidate: str) -> str:
        return f"print(bytes.fromhex({candidate.encode('utf-8').hex()!r}).decode('utf-8'))\n"

    def test_verified_report_contains_hashes_but_not_live_flag(self) -> None:
        live_flag = "FLAG{keep_this_local}"
        challenge = self._challenge(self.root, self._emit_flag(live_flag))
        solver = challenge / "solve" / "solve.py"
        manifest = challenge / "evidence" / "input-manifest.json"

        result = verification.verify_challenge(
            challenge, workspace_root=self.root, timeout_seconds=5
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.candidate, live_flag)
        report_text = result.report_path.read_text(encoding="utf-8")
        self.assertNotIn(live_flag, report_text)
        report = json.loads(report_text)
        self.assertEqual(
            report["candidate"]["sha256"],
            hashlib.sha256(live_flag.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(report["solver"]["sha256"], verification._sha256_file(solver))
        self.assertEqual(report["solve_tree"]["file_count"], 1)
        self.assertRegex(report["solve_tree"]["tree_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            report["input_manifest"]["sha256"], verification._sha256_file(manifest)
        )
        self.assertNotIn("stdout", report["execution"])
        self.assertNotIn("stderr", report["execution"])

    def test_timeout_is_bounded_and_recorded(self) -> None:
        challenge = self._challenge(
            self.root,
            "import time\ntime.sleep(10)\n" + self._emit_flag("FLAG{too_late}"),
        )

        result = verification.verify_challenge(
            challenge,
            workspace_root=self.root,
            timeout_seconds=0.1,
            max_output_bytes=1024,
        )

        self.assertFalse(result.verified)
        self.assertIsNone(result.candidate)
        self.assertEqual(result.report["status"], "solver_timeout")
        self.assertTrue(result.report["execution"]["timed_out"])
        self.assertNotIn(
            "FLAG{too_late}", result.report_path.read_text(encoding="utf-8")
        )

    @unittest.skipUnless(os.name == "nt", "Windows Job Object regression")
    def test_fast_solver_waits_for_job_assignment(self) -> None:
        challenge = self._challenge(self.root, self._emit_flag("FLAG{fast_solver}"))
        original_assign = verification._WindowsJob.assign

        def delayed_assign(job: object, process: object) -> None:
            time.sleep(0.1)
            original_assign(job, process)

        with mock.patch.object(verification._WindowsJob, "assign", delayed_assign):
            result = verification.verify_challenge(
                challenge,
                workspace_root=self.root,
                timeout_seconds=5,
                max_output_bytes=1024,
            )

        self.assertTrue(result.verified)
        self.assertEqual(result.candidate, "FLAG{fast_solver}")

    def test_background_child_is_contained_when_solver_exits(self) -> None:
        marker = self.root / "child-finished.txt"
        child_source = (
            "import pathlib, time; time.sleep(0.5); "
            f"pathlib.Path({str(marker)!r}).write_text('escaped')"
        )
        challenge = self._challenge(
            self.root,
            "import subprocess, sys\n"
            f"subprocess.Popen([sys.executable, '-c', {child_source!r}])\n"
            + self._emit_flag("FLAG{parent_exited}"),
        )
        started = time.monotonic()

        result = verification.verify_challenge(
            challenge,
            workspace_root=self.root,
            timeout_seconds=0.1,
            max_output_bytes=1024,
        )

        elapsed = time.monotonic() - started
        self.assertTrue(result.verified)
        self.assertLess(elapsed, 1.5)
        time.sleep(0.7)
        self.assertFalse(marker.exists())

    def test_detached_devnull_child_is_contained(self) -> None:
        marker = self.root / "detached-child-finished.txt"
        child_source = (
            "import pathlib, time; time.sleep(0.5); "
            f"pathlib.Path({str(marker)!r}).write_text('escaped')"
        )
        challenge = self._challenge(
            self.root,
            "import subprocess, sys\n"
            f"subprocess.Popen([sys.executable, '-c', {child_source!r}], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL, start_new_session=True)\n"
            + self._emit_flag("FLAG{detached_parent}"),
        )

        result = verification.verify_challenge(
            challenge,
            workspace_root=self.root,
            timeout_seconds=2,
            max_output_bytes=1024,
        )

        self.assertTrue(result.verified)
        time.sleep(0.7)
        self.assertFalse(marker.exists())

    def test_distinct_candidates_are_rejected(self) -> None:
        challenge = self._challenge(
            self.root,
            self._emit_flag("FLAG{one}") + self._emit_flag("FLAG{two}"),
        )

        result = verification.verify_challenge(
            challenge, workspace_root=self.root, timeout_seconds=5
        )

        self.assertFalse(result.verified)
        self.assertIsNone(result.candidate)
        self.assertEqual(result.report["status"], "multiple_distinct_flag_matches")
        serialized = result.report_path.read_text(encoding="utf-8")
        self.assertNotIn("FLAG{one}", serialized)
        self.assertNotIn("FLAG{two}", serialized)

    def test_output_limit_is_enforced(self) -> None:
        challenge = self._challenge(
            self.root,
            "import sys\nsys.stdout.write('x' * (2 * 1024 * 1024))\n",
        )

        result = verification.verify_challenge(
            challenge,
            workspace_root=self.root,
            timeout_seconds=5,
            max_output_bytes=1024,
        )

        self.assertFalse(result.verified)
        self.assertEqual(result.report["status"], "output_limit_exceeded")
        self.assertTrue(result.report["execution"]["output_limit_exceeded"])

    def test_cli_never_prints_live_candidate(self) -> None:
        live_flag = "FLAG{cli_secret}"
        challenge = self._challenge(self.root, self._emit_flag(live_flag))
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = verification.main(
                ["--workspace-root", str(self.root), str(challenge)]
            )

        self.assertEqual(code, 0)
        self.assertNotIn(live_flag, stdout.getvalue())
        self.assertNotIn(live_flag, stderr.getvalue())
        self.assertIn("candidate_sha256=", stdout.getvalue())

    def test_self_modifying_solver_is_not_verified(self) -> None:
        challenge = self._challenge(
            self.root,
            "from pathlib import Path\n"
            "path = Path(__file__)\n"
            "path.write_text(path.read_text() + '# changed\\n')\n"
            + self._emit_flag("FLAG{must_not_verify}"),
        )

        result = verification.verify_challenge(
            challenge, workspace_root=self.root, timeout_seconds=5
        )

        self.assertFalse(result.verified)
        self.assertIsNone(result.candidate)
        self.assertEqual(
            result.report["status"], "challenge_state_changed_during_execution"
        )
        self.assertNotIn(
            "FLAG{must_not_verify}", result.report_path.read_text(encoding="utf-8")
        )

    def test_solver_helper_tree_change_is_not_verified(self) -> None:
        challenge = self._challenge(
            self.root,
            "from pathlib import Path\n"
            "helper = Path(__file__).with_name('helper.py')\n"
            "helper.write_text('changed\\n')\n"
            + self._emit_flag("FLAG{helper_changed}"),
        )
        (challenge / "solve" / "helper.py").write_text("original\n", encoding="utf-8")

        result = verification.verify_challenge(
            challenge, workspace_root=self.root, timeout_seconds=5
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.report["status"], "challenge_state_changed_during_execution"
        )

    def test_preexisting_solve_cache_files_are_bound_to_proof(self) -> None:
        challenge = self._challenge(self.root, self._emit_flag("FLAG{cache_bound}"))
        cache = challenge / "solve" / "__pycache__"
        cache.mkdir()
        (cache / "dependency.pyc").write_bytes(b"intentional dependency")

        result = verification.verify_challenge(
            challenge, workspace_root=self.root, timeout_seconds=5
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.report["solve_tree"]["file_count"], 2)

    def test_malformed_or_unmatched_input_manifest_is_rejected_before_execution(self) -> None:
        challenge = self._challenge(self.root, self._emit_flag("FLAG{never_run}"))
        (challenge / "input").mkdir()
        (challenge / "input" / "sample.bin").write_bytes(b"sample")

        with self.assertRaisesRegex(
            verification.VerificationError, "do not match"
        ):
            verification.verify_challenge(
                challenge, workspace_root=self.root, timeout_seconds=5
            )

    def test_candidate_persisted_outside_local_is_rejected(self) -> None:
        live_flag = "FLAG{must_stay_local}"
        encoded = live_flag.encode("utf-8").hex()
        challenge = self._challenge(
            self.root,
            "from pathlib import Path\n"
            f"candidate = bytes.fromhex({encoded!r}).decode('utf-8')\n"
            "Path('notes.md').write_text(candidate, encoding='utf-8')\n"
            "print(candidate)\n",
        )

        result = verification.verify_challenge(
            challenge, workspace_root=self.root, timeout_seconds=5
        )

        self.assertFalse(result.verified)
        self.assertEqual(result.report["status"], "candidate_leak_detected")
        self.assertNotIn(live_flag, result.report_path.read_text(encoding="utf-8"))

    def test_catastrophic_flag_regex_is_killed(self) -> None:
        challenge = self._challenge(
            self.root,
            "print('a' * 30 + '!')\n",
        )
        (challenge / "challenge.json").write_text(
            json.dumps({"flag_regex": "(a+)+$"}), encoding="utf-8"
        )
        started = time.monotonic()

        result = verification.verify_challenge(
            challenge, workspace_root=self.root, timeout_seconds=5
        )

        self.assertFalse(result.verified)
        self.assertEqual(result.report["status"], "flag_match_timeout")
        self.assertLess(time.monotonic() - started, 5)


if __name__ == "__main__":
    unittest.main()
