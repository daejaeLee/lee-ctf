# Challenge-solving rules

These instructions apply to every challenge below `c/`.

1. Treat `input/` as immutable evidence. Work from copies in `work/`.
2. Read `challenge.json` first and stay within its `target` scope.
3. Store experiments in `work/`, raw/generated output in `output/`, selected proof in `evidence/`, and the final one-command solution in `solve/`.
4. Keep `notes.md` short: confirmed facts, ranked hypotheses, decisive results, and dead ends.
5. Use parallel work only for independent hypotheses; the lead worker consolidates `notes.md` and `solve/`.
6. Validate candidate flags against `flag_regex` and check their source before marking solved.
7. Never submit automatically. Prefer `ctf verify <challenge-path> --record`; use `ctf flag` only for a matching current proof or an explicitly manual verification.
8. Store the live flag only under `.local/`. In tracked notes, evidence, and write-ups, redact it and retain only its format, a non-reversible digest, or a `.local/` reference. This local rule overrides any skill instruction to include the real flag.
9. Have `solve/solve.py` derive the candidate at runtime and emit it on stdout. Do not hard-code or persist it; `ctf verify` scans challenge files for candidate leakage.
