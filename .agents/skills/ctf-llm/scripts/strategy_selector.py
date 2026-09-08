#!/usr/bin/env python3
"""Recommend a bounded next LLM CTF attack family from classified observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def select(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Avoid repeating a failed family; return recommendations, not payloads."""
    if not observations:
        return {"next_families": ["baseline", "direct-extraction"], "avoid": [], "reason": "no observations"}
    latest = observations[-1]
    family = str(latest.get("family", "unknown"))
    classification = latest.get("classification") or latest.get("classifier", {}).get("classification", "unknown")
    failed = {str(row.get("family")) for row in observations if row.get("classification") in {"hard_refusal", "input_block_probable", "error"}}
    matrix = {
        "success_candidate": ["verify-candidate", "minimal-reproduction"],
        "partial_leak": ["partial-reconstruction", "property-oracle", "multi-turn"],
        "input_block_probable": ["semantic-reframe", "representation", "context-reflection"],
        "hard_refusal": ["context-reflection", "semantic-reframe", "property-oracle"],
        "tool_call": ["tool-discovery", "argument-analysis"],
        "format_change": ["compare-control", "semantic-reframe", "multi-turn"],
        "error": ["baseline", "retry-bounded"],
        "session_dependent": ["fresh-vs-persisted-session", "multi-turn"],
        "unknown": ["baseline", "context-reflection", "semantic-reframe"],
    }
    candidates = matrix.get(str(classification), matrix["unknown"])
    next_families = [item for item in candidates if item not in failed and item != family]
    if not next_families:
        next_families = ["compare-control", "source-assisted-analysis"]
    return {"previous_family": family, "response": classification, "next_families": next_families,
            "avoid": sorted(failed | {family}), "reason": "response-driven pivot; do not repeat an equivalent failed family"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="classified JSONL or JSON array")
    args = parser.parse_args()
    text = Path(args.input).read_text(encoding="utf-8").strip()
    observations = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines() if line.strip()]
    print(json.dumps(select(observations), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
