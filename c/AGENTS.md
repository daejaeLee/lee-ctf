# Challenge-solving rules

These rules apply to every challenge below `c/`.

## Browser and submission

For authenticated launch, runtime inspection, or platform submission, use the
existing logged-in wmux browser (`wmux browser`) and re-snapshot after DOM
changes. Do not use an independent profile. A runtime flag claim is candidate
recovery; submission requires explicit user authorization. After authorized
submission, refresh or otherwise verify the solved state. Never track the live
candidate.

## Challenge workflow

1. Treat `input/` as immutable evidence; work from copies in `work/` and read
   `challenge.json` first. Stay within its `target` scope.
2. Keep experiments in `work/`, generated output in `output/`, selected proof
   in `evidence/`, the one-command solver in `solve/`, and concise confirmed
   facts, hypotheses, results, and dead ends in `notes.md`.
3. Parallelize only independent hypotheses; the lead worker consolidates
   `notes.md` and `solve/`.
4. Validate flags against `flag_regex` and their source before marking solved.
   Prefer `ctf verify <challenge-path> --record`; use `ctf flag` only with a
   matching current proof or explicit manual verification.
5. Keep the live flag only in `.local/`; redact tracked notes, evidence, and
   write-ups to its format, non-reversible digest, or `.local/` reference.
6. `solve/solve.py` must derive the candidate at runtime and emit stdout only;
   never hard-code or persist it. `ctf verify` checks for leakage.
