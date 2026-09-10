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

## Model orchestration

- Terra/medium coordinates normal work. Delegate independent bounded
  inventory or search to Luna/low, with `fork_turns="none"` and only the
  target path, patterns, and required result format.
- Use Terra/medium or high for analysis, PoCs, solvers, and edits. Escalate
  assembly/native reasoning, conflicting hypotheses, or two stalled attempts
  to Sol/high. Use Astra/high only after Sol lacks decisive evidence.
- When spawning a child, explicitly pass its `model` and `reasoning_effort`;
  role names alone inherit the parent model in the current runtime. Do not
  delegate work that is cheaper to perform directly. Return implementation and
  repetitive changes to Terra or Luna after deep analysis.

## Memory

- `notes.md`, `evidence/`, current artifacts, and reproducible solver output
  are authoritative for the active challenge. Use claude-mem only for
  cross-session recall and related previous work.
- On resumed work, search memory when prior work is likely relevant or the
  current state is unclear; verify every remembered conclusion against current
  artifacts. Never treat memory as evidence.
- Keep decisive facts, validated hypotheses, and important dead ends in
  `notes.md`. Do not duplicate the entire active challenge state into memory
  files.

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
- For authenticated web CTFs, use the existing browser only to establish or
  obtain the authorized session, launch URL, short-lived token, or other
  runtime material. Once those values are obtained, prefer a reproducible
  `curl.exe` or in-page `fetch` request sequence for recon, solving, flag
  claim, and authorized submission. Do not rely on fragile UI field filling
  or stale accessibility references when an equivalent documented request is
  available. Keep every request within the challenge's declared hosts and
  preserve token/seed/proof instance affinity.
- Use challenge-local environments when dependencies conflict. Interact only
  with hosts, ports, URLs, accounts, and files named by challenge metadata or
  explicitly supplied by the user.
