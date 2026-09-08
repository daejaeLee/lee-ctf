#!/usr/bin/env python3
"""Produce deterministic, bounded prompt representations for authorized CTF probes."""

from __future__ import annotations

import argparse
import base64
import json
from urllib.parse import quote


def mutate(text: str, transform: str) -> str:
    if transform == "case":
        return text.swapcase()
    if transform == "whitespace":
        return " ".join(text.split())
    if transform == "fragment":
        return " ".join(text)
    if transform == "base64":
        return base64.b64encode(text.encode("utf-8")).decode("ascii")
    if transform == "hex":
        return text.encode("utf-8").hex()
    if transform == "url":
        return quote(text, safe="")
    if transform == "reverse":
        return text[::-1]
    if transform == "json":
        return json.dumps(text, ensure_ascii=False)
    raise ValueError(f"unsupported transform: {transform}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transform", choices=("case", "whitespace", "fragment", "base64", "hex", "url", "reverse", "json"), required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    print(mutate(args.text, args.transform))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
