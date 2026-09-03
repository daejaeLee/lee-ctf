# Notes

## Confirmed facts

- The authenticated Practice page launches the isolated runtime under slug
  `dosage-calculator-overflow`.
- The runtime accepts a POST to its same-origin dosage API with JSON fields
  `medication`, `dose_mg`, and `frequency_per_day`; an `override_token` is the
  proof code for the flag claim.
- `Amoxicillin`, `dose_mg: 65536`, and `frequency_per_day: 1` trigger the
  legacy 16-bit arithmetic overflow and return the override proof.
- The platform's runtime is deliberately cookie-free; final account credit is
  recorded only through the authenticated Practice submission form.

## Hypotheses

| Priority | Hypothesis | Fastest test | Result / next step |
| --- | --- | --- | --- |
| 1 | A legacy-width arithmetic overflow returns an override proof. | Send a bounded overflow input to the documented dosage API. | Confirmed with `65536 × 1` |

## Verified result

- The runtime claim produced a candidate matching the expected `SDG{...}`
  format. The authenticated Practice form accepted it.
- A page refresh showed **Dosage Calculator Overflow** as solved; aggregate
  progress changed to 11 solved challenges and 3400 total points.
- The candidate is intentionally not recorded. Its SHA-256 digest is in
  `evidence/proof.md`.

## Timing

| Milestone | Elapsed from solver command start |
| --- | ---: |
| Candidate printed to stdout | 5.902335 s |
| Practice submission accepted | 641.402161 s |
| Refreshed solve-state verification | 662.631993 s |

## Timeline and dead ends

- The Practice form required browser keystroke input rather than a DOM-only
  value fill so its client state would be populated before submission.
