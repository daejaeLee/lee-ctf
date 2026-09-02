# {{CHALLENGE_NAME}} scope

- Event: `{{EVENT}}`
- Category: `{{CATEGORY}}`
- Primary skill: `{{SKILL}}`
- Authorized target: `{{TARGET}}`
- Work only on files and targets declared in this directory's `challenge.json` or explicitly added by the user.
- Never modify `input/` in place. Use `work/` for experiments and `solve/` for the final reproducible path.
- Do not submit a recovered flag automatically.
- Keep the live flag only under `.local/`. Redact it from tracked notes, evidence, and write-ups even if a skill asks for the real value.
- Have `solve/solve.py` derive the candidate at runtime and emit it on stdout without hard-coding or persisting it; verification scans challenge files for leakage.
