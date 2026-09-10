# Challenge-solving rules

These rules apply to every challenge below `c/`.

## Browser and submission

Use the existing logged-in wmux browser (`wmux browser`) only to establish the
authenticated session or obtain launch URLs, short-lived tokens, and other
runtime material; do not use an independent profile. Then prefer deterministic
`curl.exe` or in-page `fetch` requests for runtime inspection, solving, flag
claim, and authorized platform submission. This avoids fragile UI field
filling and stale DOM/accessibility references. Keep each launch token,
artifact seed, proof, and claim in the same runtime instance; never replay a
spent token or mix values across launches. A runtime flag claim is candidate
recovery; submission requires explicit user authorization. After authorized
submission, refresh or query the platform's documented state endpoint to
verify the solved state. Never track the live candidate.

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
