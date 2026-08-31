# Challenge-solving rules

These instructions apply to every challenge below `c/`.

1. Treat `input/` as immutable evidence. Work from copies in `work/`.
2. Read `challenge.json` first and stay within its `target` scope.
3. Store experiments in `work/`, raw/generated output in `output/`, selected proof in `evidence/`, and the final one-command solution in `solve/`.
4. Keep `notes.md` short: confirmed facts, ranked hypotheses, decisive results, and dead ends.
5. Use parallel work only for independent hypotheses; the lead worker consolidates `notes.md` and `solve/`.
6. Validate candidate flags against `flag_regex` and check their source before marking solved.
7. Never submit automatically. Record a verified flag with `ctf flag <challenge-path>`.
