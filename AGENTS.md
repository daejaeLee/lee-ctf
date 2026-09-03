# CTF workspace

Authorized CTF challenges and user-supplied assets only. Optimize for fast,
reproducible flag recovery; work autonomously with reversible workspace
changes. Ask only when scope, credentials, a destructive action, or an
external state change is unclear. Never submit a flag or contact a third party
without explicit authorization.

## Start

1. Read the nearest `AGENTS.md`, `challenge.json`, and challenge `README.md`.
2. Preserve `input/`; hash or inspect it before copying into `work/`.
3. Route a known category directly to its `ctf-*` skill; use
   `solve-challenge` only for ambiguous or cross-category triage.
4. Run only independent cheap checks in parallel, using separate
   `work/agents/<name>/` directories. Record decisive facts, hypotheses, and
   dead ends in short `notes.md`.
5. Put the smallest reproducible solver in `solve/` and selected proof in
   `evidence/`. Use `ctf-writeup` only after validation and reproducibility.

## Skill routing

| Category | Skill |
| --- | --- |
| AI / ML | `ctf-ai-ml` |
| Crypto | `ctf-crypto` |
| Forensics | `ctf-forensics` |
| Malware | `ctf-malware` |
| Misc / language jail | `ctf-misc` |
| OSINT | `ctf-osint` |
| Binary exploitation | `ctf-pwn` |
| Reverse engineering | `ctf-reverse` |
| Web | `ctf-web` |

- Start with `ctf-reverse` when native behavior is unknown; use `ctf-pwn`
  once the exploit primitive is understood.
- Python/Bash/eval/AST jails use `ctf-misc`; native syscall, seccomp, kernel,
  container, or process-isolation escapes use `ctf-pwn`.
- Use `ctf-malware` for malicious behavior/C2/config extraction,
  `ctf-forensics` for supplied evidence reconstruction, and `ctf-osint` only
  when public-source discovery is the intended path.
- Add a second category only when evidence crosses that boundary. For
  on-demand source-audit, parsing, or EVM-hashing guidance, read
  `shared/ctf-ecc-on-demand.md`; do not load it by default.

## Evidence and safety

- Search with `rg` first; prefer deterministic scripts, timeouts, and
  checkpoints. Revisit assumptions after two failed variants or ten minutes
  without evidence.
- Keep live flags only in `.local/`. Solvers derive a candidate at runtime and
  print it to stdout; tracked notes, proof, and write-ups redact it.
- Do not mark solved until format, provenance, and one reproduction agree.
- Do not modify vendored `.agents/skills`; put local helpers in `shared/` or
  `scripts/`. Never reset, clean, overwrite, or cross-contaminate another
  challenge directory.

## Environment and boundary

- Use PowerShell 5.1-compatible host scripts and `curl.exe`. Prefer Kali WSL
  for Linux-first pwn, reverse, forensics, and malware work; never execute an
  unknown malware sample on Windows.
- Use challenge-local environments when dependencies conflict. Interact only
  with hosts, ports, URLs, accounts, and files named by challenge metadata or
  explicitly supplied by the user.
