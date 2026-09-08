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
CLASSIFIER_SPEC = importlib.util.spec_from_file_location("response_classifier", Path(__file__).with_name("response_classifier.py"))
assert CLASSIFIER_SPEC and CLASSIFIER_SPEC.loader
response_classifier = importlib.util.module_from_spec(CLASSIFIER_SPEC)
CLASSIFIER_SPEC.loader.exec_module(response_classifier)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--prompts", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-probes", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--family", default="campaign")
    parser.add_argument("--stop-on-candidate", action="store_true")
    parser.add_argument("--session", help="replace {{session}} in target config")
    args = parser.parse_args()
    if args.max_probes < 1 or args.max_probes > 200:
        parser.error("--max-probes must be between 1 and 200")
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    prompts = Path(args.prompts).read_text(encoding="utf-8").splitlines()
    with Path(args.output).open("a", encoding="utf-8", newline="\n") as output:
        for index, prompt in enumerate((item for item in prompts if item.strip()), start=1):
            if index > args.max_probes:
                break
            result = llm_probe.probe(config, prompt, session=args.session)
            result.update({"id": index, "family": args.family, "prompt": prompt})
            result["classifier"] = response_classifier.classify(result)
            output.write(json.dumps(result, ensure_ascii=False) + "\n")
            if result["signals"]["candidate"] and args.stop_on_candidate:
                break
            if args.delay:
                time.sleep(args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
