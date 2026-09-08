#!/usr/bin/env python3
"""Run a finite prompt list through llm_probe without storing credentials in JSONL."""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("llm_probe", Path(__file__).with_name("llm_probe.py"))
assert SPEC and SPEC.loader
llm_probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(llm_probe)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--prompts", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-probes", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--family", default="campaign")
    parser.add_argument("--stop-on-candidate", action="store_true")
    args = parser.parse_args()
    if args.max_probes < 1 or args.max_probes > 200:
        parser.error("--max-probes must be between 1 and 200")
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    prompts = Path(args.prompts).read_text(encoding="utf-8").splitlines()
    with Path(args.output).open("a", encoding="utf-8", newline="\n") as output:
        for index, prompt in enumerate((item for item in prompts if item.strip()), start=1):
            if index > args.max_probes:
                break
            result = llm_probe.probe(config, prompt)
            result.update({"id": index, "family": args.family, "prompt": prompt})
            output.write(json.dumps(result, ensure_ascii=False) + "\n")
            if result["signals"]["candidate"] and args.stop_on_candidate:
                break
            if args.delay:
                time.sleep(args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
