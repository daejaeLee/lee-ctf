#!/usr/bin/env python3
"""Run a bounded multi-turn prompt sequence with explicit fresh/persisted session IDs."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("llm_probe", Path(__file__).with_name("llm_probe.py"))
assert SPEC and SPEC.loader
llm_probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(llm_probe)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--turns", required=True, help="JSON list of {prompt, family} objects")
    parser.add_argument("--output", required=True)
    parser.add_argument("--session", default="session-1")
    parser.add_argument("--fresh-each-turn", action="store_true")
    parser.add_argument("--stop-on-candidate", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    turns = json.loads(Path(args.turns).read_text(encoding="utf-8"))
    if not isinstance(turns, list) or not 1 <= len(turns) <= 30:
        parser.error("--turns must contain 1..30 turns")
    with Path(args.output).open("a", encoding="utf-8", newline="\n") as out:
        for number, turn in enumerate(turns, 1):
            if not isinstance(turn, dict) or not isinstance(turn.get("prompt"), str):
                parser.error("every turn needs a prompt string")
            session = f"{args.session}-{number}" if args.fresh_each_turn else args.session
            result = llm_probe.probe(config, turn["prompt"], session=session)
            result.update({"id": number, "turn": number, "session": session, "family": turn.get("family", "multi-turn"), "prompt": turn["prompt"]})
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            if args.stop_on_candidate and result["signals"]["candidate"]:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
