from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import io
import json
import shutil
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


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
        ctf.MODEL_ROUTING = self.root / ".ctf" / "model-routing.json"
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
        ctf.write_json(ctf.MODEL_ROUTING, ctf.read_json(PROJECT_ROOT / ".ctf" / "model-routing.json"))

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_slugify_and_alias(self) -> None:
        self.assertEqual(ctf.slugify("Baby SQLi"), "baby-sqli")
        self.assertEqual(ctf.normalize_category("rev"), "reverse")

    def routing_challenge(self, name: str = "gate") -> Path:
        create = argparse.Namespace(event="Routing", category="web", name=name, source_url=None, target_url=None, url=None, host=None, port=None, flag_regex=r"FLAG\{[^}]+\}")
        self.assertEqual(ctf.cmd_new(create), 0)
        return self.root / "c" / "routing" / "web" / name

    def checkpoint(self, challenge: Path, primitive_id: str, *, variant: str = "", model: str = "terra", sol_outcome: str | None = None, astra_outcome: str | None = None) -> int:
        return ctf.cmd_checkpoint(argparse.Namespace(
            challenge=str(challenge), strategy=primitive_id, primitive=None, primitive_id=primitive_id,
            variant=variant, result="fail", independent=True, evidence="test evidence", model=model,
            native_critical=False, conflicting_hypotheses=False, sol_outcome=sol_outcome,
            astra_outcome=astra_outcome,
        ))

    def test_second_sol_escalation_cycle(self) -> None:
        challenge = self.routing_challenge()
        self.assertEqual(self.checkpoint(challenge, "auth-boundary"), 0)
        self.assertEqual(self.checkpoint(challenge, "parser-state"), 0)
        self.assertEqual(ctf.evaluate_routing(ctf.load_routing_state(challenge), ctf.routing_policy())["action"], "ESCALATE_SOL")
        self.assertEqual(self.checkpoint(challenge, "sol-analysis", model="sol", sol_outcome="decisive"), 0)
        state = ctf.load_routing_state(challenge)
        self.assertEqual(state["routing_epoch"], 1)
        self.assertEqual(ctf.evaluate_routing(state, ctf.routing_policy())["action"], "CONTINUE_TERRA")
        self.assertEqual(self.checkpoint(challenge, "state-desync"), 0)
        self.assertEqual(self.checkpoint(challenge, "cache-boundary"), 0)
        self.assertEqual(ctf.evaluate_routing(ctf.load_routing_state(challenge), ctf.routing_policy())["action"], "ESCALATE_SOL")

    def test_astra_decisive_and_blocked_transitions(self) -> None:
        challenge = self.routing_challenge("astra-decisive")
        self.checkpoint(challenge, "first")
        self.checkpoint(challenge, "second")
        self.checkpoint(challenge, "sol-analysis", model="sol", sol_outcome="unresolved")
        self.assertEqual(ctf.evaluate_routing(ctf.load_routing_state(challenge), ctf.routing_policy())["action"], "ESCALATE_ASTRA")
        self.checkpoint(challenge, "astra-analysis", model="astra", astra_outcome="decisive")
        state = ctf.load_routing_state(challenge)
        self.assertEqual(state["routing_epoch"], 1)
        self.assertEqual(ctf.evaluate_routing(state, ctf.routing_policy())["action"], "CONTINUE_TERRA")

        blocked = self.routing_challenge("astra-blocked")
        self.checkpoint(blocked, "first")
        self.checkpoint(blocked, "second")
        self.checkpoint(blocked, "sol-analysis", model="sol", sol_outcome="unresolved")
        self.checkpoint(blocked, "astra-analysis", model="astra", astra_outcome="blocked")
        self.assertEqual(ctf.evaluate_routing(ctf.load_routing_state(blocked), ctf.routing_policy())["action"], "BLOCKED")
        complete = argparse.Namespace(challenge=str(blocked), state="BLOCKED_WITH_REPRODUCIBLE_REASON", reason="reproduced target limit", evidence="evidence/repro.txt")
        self.assertEqual(ctf.cmd_complete(complete), 0)

    def test_initial_timeout_and_primitive_variant_accounting(self) -> None:
        challenge = self.routing_challenge("timeout")
        state = ctf.load_routing_state(challenge)
        state["started_at"] = "2026-01-01T00:00:00Z"
        ctf.persist_routing_state(challenge, state, ctf.routing_policy())
        now = ctf.datetime(2026, 1, 1, 0, 10, tzinfo=ctf.timezone.utc)
        self.assertEqual(ctf.evaluate_routing(state, ctf.routing_policy(), now)["action"], "ESCALATE_SOL")

        variants = self.routing_challenge("variants")
        for variant in ("urlencode", "double-urlencode", "delimiter-change"):
            self.checkpoint(variants, "parser-confusion", variant=variant)
        state = ctf.load_routing_state(variants)
        self.assertEqual(ctf.routing_summary(state, ctf.routing_policy())["failures"], 1)
        self.checkpoint(variants, "auth-boundary")
        self.assertEqual(ctf.evaluate_routing(ctf.load_routing_state(variants), ctf.routing_policy())["action"], "ESCALATE_SOL")

    def test_native_and_conflicting_hypothesis_triggers_remain_mandatory(self) -> None:
        challenge = self.routing_challenge("special-triggers")
        state = ctf.load_routing_state(challenge)
        state["native_critical"] = True
        self.assertEqual(ctf.evaluate_routing(state, ctf.routing_policy())["reason"], "native_or_assembly_critical_path")
        state["native_critical"] = False
        state["conflicting_hypotheses"] = True
        self.assertEqual(ctf.evaluate_routing(state, ctf.routing_policy())["action"], "ESCALATE_SOL")

    def test_checkpoint_and_completion_gates(self) -> None:
        challenge = self.routing_challenge("completion")
        self.checkpoint(challenge, "first")
        self.checkpoint(challenge, "second")
        with self.assertRaisesRegex(ValueError, "Sol escalation is required"):
            self.checkpoint(challenge, "one-more")
        with self.assertRaisesRegex(ValueError, "cannot complete while mandatory escalation"):
            ctf.cmd_complete(argparse.Namespace(challenge=str(challenge), state="USER_GOAL_COMPLETED", reason="done", evidence="evidence/proof.json"))

        fresh = self.routing_challenge("not-escalated")
        with self.assertRaisesRegex(ValueError, "ESCALATED completion requires"):
            ctf.cmd_complete(argparse.Namespace(challenge=str(fresh), state="ESCALATED", reason="handoff", evidence=""))
        with self.assertRaisesRegex(ValueError, "blocked completion requires"):
            ctf.cmd_complete(argparse.Namespace(challenge=str(fresh), state="BLOCKED_WITH_REPRODUCIBLE_REASON", reason="target unavailable", evidence=""))

    def test_project_config_drives_parser_defaults(self) -> None:
        config = ctf.read_json(ctf.CTF_CONFIG)
        config["default_event"] = "speedrun-2026"
        config["default_flag_regex"] = r"FLAG\{[^}]+\}"
        ctf.write_json(ctf.CTF_CONFIG, config)

        args = ctf.build_parser().parse_args(["new", "--category", "web", "--name", "demo"])
        self.assertEqual(args.event, "speedrun-2026")
        self.assertEqual(args.flag_regex, r"FLAG\{[^}]+\}")

    def test_verify_parser_accepts_options_after_challenge_and_solver_separator(self) -> None:
        args = ctf.build_parser().parse_args(
            ["verify", "c/example", "--timeout", "5", "--", "--mode", "fast"]
        )
        self.assertEqual(args.timeout, 5.0)
        self.assertEqual(args.solver_args, ["--mode", "fast"])

    def test_doctor_modes_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            ctf.build_parser().parse_args(["doctor", "--project-only", "--wsl-tools"])

    @unittest.skipUnless(ctf.os.name == "nt", "Windows path mapping")
    def test_windows_workspace_path_maps_to_wsl_mount(self) -> None:
        self.assertEqual(
            ctf.windows_path_to_wsl(Path(r"C:\lee-ctf")),
            "/mnt/c/lee-ctf",
        )

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

    def test_malformed_skills_lock_is_reported_cleanly(self) -> None:
        ctf.write_json(ctf.SKILLS_LOCK, ["not", "an", "object"])
        args = argparse.Namespace(
            skills_root=str(ctf.SKILLS_ROOT),
            commit=None,
            output=str(ctf.SKILLS_MANIFEST),
        )
        with self.assertRaisesRegex(ValueError, "JSON root must be an object"):
            ctf.cmd_skills_manifest(args)
        with self.assertRaisesRegex(ValueError, "JSON root must be an object"):
            ctf.build_parser()

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
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(ctf.cmd_triage(triage), 0)
        report_text = (challenge / "work" / "triage.json").read_text(encoding="utf-8")
        report = json.loads(report_text)
        self.assertEqual(report["files"][0]["type"], "PNG")
        self.assertEqual(
            report["flag_candidates"][0]["sha256"],
            ctf._candidate_sha256("flag{self_test}"),
        )
        self.assertNotIn("flag{self_test}", report_text)
        self.assertNotIn("flag{self_test}", stdout.getvalue())
        local_triage = (self.root / ".local" / "triage-candidates.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("flag{self_test}", local_triage)

        record = argparse.Namespace(
            challenge=str(challenge),
            value="flag{self_test}",
            allow_nonmatching=False,
            allow_unverified=True,
        )
        self.assertEqual(ctf.cmd_flag(record), 0)
        metadata = json.loads((challenge / "challenge.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "solved")
        self.assertNotIn("flag{self_test}", (challenge / "challenge.json").read_text(encoding="utf-8"))

    def test_new_separates_source_and_target_urls(self) -> None:
        create = argparse.Namespace(
            event="Example 2026",
            category="web",
            name="URL Split",
            source_url="https://ctf.example/challenges/1",
            target_url="https://target.example/",
            url=None,
            host=None,
            port=None,
            flag_regex=r"FLAG\{[^}]+\}",
        )
        self.assertEqual(ctf.cmd_new(create), 0)
        challenge = self.root / "c" / "example-2026" / "web" / "url-split"
        metadata = ctf.read_json(challenge / "challenge.json")
        self.assertEqual(metadata["source_url"], create.source_url)
        self.assertEqual(metadata["target"]["url"], create.target_url)

    def test_verify_proof_gates_flag_recording(self) -> None:
        create = argparse.Namespace(
            event="Proof 2026",
            category="misc",
            name="Proof Gate",
            source_url=None,
            target_url=None,
            url=None,
            host=None,
            port=None,
            flag_regex=r"FLAG\{[^}]+\}",
        )
        self.assertEqual(ctf.cmd_new(create), 0)
        challenge = self.root / "c" / "proof-2026" / "misc" / "proof-gate"
        live_flag = "FLAG{verified_locally}"
        (challenge / "solve" / "solve.py").write_text(
            f"print(bytes.fromhex({live_flag.encode('utf-8').hex()!r}).decode('utf-8'))\n",
            encoding="utf-8",
        )

        unverified = argparse.Namespace(
            challenge=str(challenge),
            value=live_flag,
            allow_nonmatching=False,
            allow_unverified=False,
        )
        with self.assertRaisesRegex(ValueError, "verification proof"):
            ctf.cmd_flag(unverified)

        verify = argparse.Namespace(
            challenge=str(challenge),
            timeout=5.0,
            max_output_mb=1.0,
            solver_args=[],
            record=False,
        )
        self.assertEqual(ctf.cmd_verify(verify), 0)
        proof = (challenge / "evidence" / "solve-verification.json").read_text(encoding="utf-8")
        self.assertNotIn(live_flag, proof)
        late_input = challenge / "input" / "late.bin"
        late_input.write_bytes(b"changed after verification")
        with self.assertRaisesRegex(ValueError, "input artifacts"):
            ctf.cmd_flag(unverified)
        late_input.unlink()
        helper = challenge / "solve" / "helper.py"
        helper.write_text("changed after verification\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "solve tree"):
            ctf.cmd_flag(unverified)
        helper.unlink()
        metadata_path = challenge / "challenge.json"
        metadata = ctf.read_json(metadata_path)
        original_target = dict(metadata["target"])
        metadata["target"]["url"] = "https://changed.example/"
        ctf.write_json_atomic(metadata_path, metadata)
        with self.assertRaisesRegex(ValueError, "scope changed"):
            ctf.cmd_flag(unverified)
        metadata["target"] = original_target
        ctf.write_json_atomic(metadata_path, metadata)
        notes_path = challenge / "notes.md"
        original_notes = notes_path.read_bytes()
        notes_path.write_bytes(original_notes + b"tracked change\n")
        with self.assertRaisesRegex(ValueError, "protected challenge files changed"):
            ctf.cmd_flag(unverified)
        notes_path.write_bytes(original_notes)
        self.assertEqual(ctf.cmd_flag(unverified), 0)

    def test_agent_work_isolated_and_no_overwrite(self) -> None:
        create = argparse.Namespace(
            event="Agents 2026",
            category="reverse",
            name="Parallel",
            source_url=None,
            target_url=None,
            url=None,
            host=None,
            port=None,
            flag_regex=r"FLAG\{[^}]+\}",
        )
        self.assertEqual(ctf.cmd_new(create), 0)
        challenge = self.root / "c" / "agents-2026" / "reverse" / "parallel"
        work = argparse.Namespace(challenge=str(challenge), name="Static Pass", reuse=False)
        self.assertEqual(ctf.cmd_agent_work(work), 0)
        findings = challenge / "work" / "agents" / "static-pass" / "findings.md"
        self.assertTrue(findings.is_file())
        with self.assertRaisesRegex(ValueError, "already exists"):
            ctf.cmd_agent_work(work)

        reserved = argparse.Namespace(challenge=str(challenge), name="CON.txt", reuse=False)
        self.assertEqual(ctf.cmd_agent_work(reserved), 0)
        self.assertTrue(
            (challenge / "work" / "agents" / "_con.txt" / "findings.md").is_file()
        )

    def test_agent_work_same_name_is_created_atomically(self) -> None:
        challenge = self.root / "c" / "agents" / "misc" / "atomic"
        (challenge / "work").mkdir(parents=True)
        ctf.write_json(challenge / "challenge.json", {"flag_regex": r"FLAG\{[^}]+\}"})
        args = argparse.Namespace(challenge=str(challenge), name="Same Agent", reuse=False)

        def create_agent() -> str:
            try:
                ctf.cmd_agent_work(args)
                return "created"
            except ValueError:
                return "exists"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _value: create_agent(), range(2)))
        self.assertCountEqual(results, ["created", "exists"])

    def test_agent_work_rejects_reparse_like_work_directory(self) -> None:
        challenge = self.root / "c" / "agents" / "misc" / "unsafe"
        (challenge / "work").mkdir(parents=True)
        ctf.write_json(challenge / "challenge.json", {"flag_regex": r"FLAG\{[^}]+\}"})
        original = ctf._is_link_like

        def link_check(path: Path) -> bool:
            return Path(path) == challenge / "work" or original(Path(path))

        args = argparse.Namespace(challenge=str(challenge), name="Agent", reuse=False)
        with mock.patch.object(ctf, "_is_link_like", side_effect=link_check):
            with self.assertRaisesRegex(ValueError, "link or junction"):
                ctf.cmd_agent_work(args)

    def test_parallel_flag_storage_keeps_every_challenge(self) -> None:
        challenges: list[Path] = []
        for index in range(8):
            challenge = self.root / "c" / "flags" / "misc" / f"challenge-{index}"
            challenge.mkdir(parents=True)
            ctf.write_json(
                challenge / "challenge.json",
                {"flag_regex": r"FLAG\{[^}]+\}", "status": "new", "solved_at": None},
            )
            challenges.append(challenge)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(ctf._store_flag, challenge, {}, f"FLAG{{value_{index}}}")
                for index, challenge in enumerate(challenges)
            ]
            for future in futures:
                future.result(timeout=10)

        flags = ctf.read_json(ctf.LOCAL_FLAGS)
        self.assertEqual(len(flags), len(challenges))
        for challenge in challenges:
            metadata = ctf.read_json(challenge / "challenge.json")
            self.assertEqual(metadata["status"], "solved")

    def test_flag_metadata_failure_restores_local_store(self) -> None:
        challenge = self.root / "c" / "flags" / "misc" / "rollback"
        challenge.mkdir(parents=True)
        metadata_path = challenge / "challenge.json"
        ctf.write_json(
            metadata_path,
            {"flag_regex": r"FLAG\{[^}]+\}", "status": "new", "solved_at": None},
        )
        metadata_before = metadata_path.read_bytes()
        original = ctf.write_json_atomic
        failed_once = False

        def fail_metadata(path: Path, value: object) -> None:
            nonlocal failed_once
            if Path(path) == metadata_path and not failed_once:
                failed_once = True
                raise OSError("simulated metadata failure")
            original(Path(path), value)

        with mock.patch.object(ctf, "write_json_atomic", side_effect=fail_metadata):
            with self.assertRaisesRegex(OSError, "simulated metadata failure"):
                ctf._store_flag(challenge, {}, "FLAG{rollback}")
        self.assertFalse(ctf.LOCAL_FLAGS.exists())
        self.assertEqual(metadata_path.read_bytes(), metadata_before)


if __name__ == "__main__":
    unittest.main()
