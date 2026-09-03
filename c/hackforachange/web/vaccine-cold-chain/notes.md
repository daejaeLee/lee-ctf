# Notes

## Confirmed facts

- The practice listing identifies this as challenge ID `7adc7b47-9d8d-4370-81e4-e587362b2401`, runtime slug `vaccine-cold-chain`, worth 50 points.
- The challenge runtime requires a launch token and redeems it for an instance-specific `artifact_seed`.
- Intended flow: `GET /api/vaccine-cold-chain?seed=<seed>&action=status` returns a session credential; `POST` with that credential and `action=generate_report` returns the proof code used to claim the flag.
- The normal `launch-challenge` endpoint returned HTTP 401 without an authenticated account session (2026-09-02 15:17 KST).
- Launch tokens are single-use: the supplied launch URL had already been redeemed by the opened runtime, and a second redemption returned `Invalid token`.
- With the artifact seed, the status endpoint and the report-generation endpoint both returned HTTP 200. The report response contained the expected proof token.
- Replaying the already-redeemed launch token to `claim-runtime-flag` returned HTTP 400 `Invalid request`; no flag was persisted or exposed in tracked files.
- A fresh authenticated launch provided a new runtime token and seed. The status → report → claim sequence returned a candidate matching `flag_regex`.
- The candidate was submitted through the authenticated Practice UI. A server refresh confirmed the card is marked `Solved`, with the account total changing from 8 / 3150 to 9 / 3200. The live value is not recorded here.

## Hypotheses

| Priority | Hypothesis | Fastest test | Result / next step |
| --- | --- | --- | --- |
| 1 | Status → report → claim | Fresh runtime API chain. | Completed and submitted; server-side Practice record verified. |
| 1 | Recover the opened runtime's artifact seed, then reproduce the status → report flow. | Copy the displayed `SEED` from the runtime Session panel. | Waiting for the artifact seed. |
| 1 | Claim the flag with an active runtime session, then submit it through the authenticated practice page. | Use the already-open runtime tab's Claim Flag control. | Blocked: no controllable authenticated browser session is connected. |

## Timeline and dead ends

- Started investigation: 2026-09-02 15:15:01 KST.
- Completed through the authorized authenticated browser session; server-side record verified after refresh.
