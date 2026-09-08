#!/usr/bin/env python3
"""Extract unique flag-like candidates from JSONL responses."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl")
    parser.add_argument("--flag-regex", default=r"(?i)[a-z0-9_]+\{[^}\r\n]+\}")
    args = parser.parse_args()
    pattern = re.compile(args.flag_regex)
    values: list[str] = []
    for line in Path(args.jsonl).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for match in pattern.findall(str(row.get("response", ""))):
            if match not in values:
                values.append(match)
    for value in values:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
