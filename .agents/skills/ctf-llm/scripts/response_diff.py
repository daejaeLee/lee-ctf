#!/usr/bin/env python3
"""Summarize response differential signals from a campaign JSONL."""

from __future__ import annotations

import argparse
import json
from difflib import SequenceMatcher
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl")
    args = parser.parse_args()
    rows = [json.loads(line) for line in Path(args.jsonl).read_text(encoding="utf-8").splitlines() if line]
    if not rows:
        return 0
    base = str(rows[0].get("response", ""))
    for row in rows:
        response = str(row.get("response", ""))
        print(json.dumps({"id": row.get("id"), "status": row.get("status"), "length": len(response), "similarity_to_first": round(SequenceMatcher(None, base, response).ratio(), 4), "signals": row.get("signals", {})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
