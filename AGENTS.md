# CTF workspace

This repository is dedicated to authorized Capture The Flag challenges and challenge assets supplied by the user.

## Objective

- Optimize for the fastest reproducible flag recovery.
- Proceed autonomously with reversible operations inside this workspace.
- Ask only when target scope, required credentials, a destructive action, or an external state change is genuinely unclear.
- Never submit a flag or contact a third party unless the user explicitly asks.

## Start protocol

1. Read the nearest `AGENTS.md`, `challenge.json`, and challenge `README.md`.
2. Preserve files under `input/`; inspect or hash them before copying into `work/`.
3. If the category is clear, use its matching `ctf-*` skill directly. Use `solve-challenge` for ambiguous or cross-category triage.
4. Run cheap independent checks in parallel. Give parallel agents separate `work/agents/<name>/` directories.
5. Keep decisive facts, hypotheses, failed paths, and next actions in `notes.md`.
6. Put the smallest reproducible final solution in `solve/` and curated proof in `evidence/`.
7. Use `ctf-writeup` only after the flag is validated and the solve is reproducible.

## Skill routing

| Category | Skill |
| --- | --- |
| AI / ML | `ctf-ai-ml` |
| Crypto | `ctf-crypto` |
| Forensics | `ctf-forensics` |
| Malware | `ctf-malware` |
| Misc / jail | `ctf-misc` |
| OSINT | `ctf-osint` |
| Binary exploitation | `ctf-pwn` |
| Reverse engineering | `ctf-reverse` |
| Web | `ctf-web` |

Use `ctf-reverse` before `ctf-pwn` when the binary's behavior or vulnerability is not understood. Add a second category skill when evidence shows a cross-category chain.

Local routing overrides take precedence over broader or vendored routing guidance:

- Route AI/ML challenges directly to `ctf-ai-ml`, including adversarial models, model extraction, training-data attacks, and LLM prompt-injection challenges.
- Route Python, Bash, `eval`, AST, restricted-builtins, and language-level jails to `ctf-misc`. Route native syscall, seccomp, kernel, container, or process-isolation escapes to `ctf-pwn`; start with `ctf-reverse` if the native program's behavior is still unknown.
- Use `ctf-malware` when malicious behavior, C2/config extraction, indicators, unpacking, or anti-analysis is central. Use `ctf-reverse` when understanding compiled or obfuscated program logic is central. Use `ctf-forensics` when evidence acquisition or reconstruction from disks, memory, logs, or packet captures is central. Add the next skill only when the evidence crosses that boundary.
- Use `ctf-osint` only for discovery from public sources. An unknown hash, coordinate, username, or identifier is OSINT only when public-source lookup is the intended path; analyze supplied artifacts with the relevant crypto, forensics, malware, or reverse skill.

## Execution rules

- Search with `rg`/`rg --files` first when available.
- Prefer deterministic scripts over long manual command histories.
- Put timeouts on network calls, brute force, fuzzers, and symbolic execution. Checkpoint expensive searches.
- Revisit assumptions after two failed variants or ten minutes without new evidence.
- Keep secrets and live flag values only in `.local/`; it is ignored by Git. Do not place a live flag in tracked metadata, notes, evidence, or write-ups.
- Have reproducible solvers emit the candidate on stdout without hard-coding or persisting it; `ctf verify` rejects candidate bytes found outside immutable `input/` or `.local/`.
- Local flag policy overrides `ctf-writeup` guidance: tracked write-ups must redact the recovered value and may retain only the flag format, a non-reversible digest, or a reference to `.local/`.
- Do not claim a solve until the candidate matches the expected format, is tied to the intended artifact or service, and can be reproduced once.
- Do not modify vendored files under `.agents/skills`; put local helpers under `shared/` or `scripts/`.
- Do not clean, overwrite, or reset another challenge directory.

## Environment

- Windows PowerShell 5.1 is the host orchestration shell. Scripts must remain PS 5.1 compatible.
- Use `curl.exe` explicitly; `curl` is a PowerShell alias on this host.
- Prefer Kali WSL for Linux-first pwn, reverse, forensics, and malware tools. Treat WSL availability and WSL execution permission as separate checks.
- Prefer a challenge-local environment when dependencies conflict. Do not force Linux-only packages into the host Python installation.
- Never execute an unknown malware sample directly on the Windows host. Use an isolated disposable environment.

## Authorized target boundary

Only interact with hosts, ports, URLs, accounts, and files identified by the challenge metadata or explicitly placed in scope by the user. Do not broaden scanning to unrelated infrastructure.
