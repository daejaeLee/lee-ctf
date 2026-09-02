# lee-ctf

Fast, reproducible workspace for authorized CTF challenges. The project keeps original inputs immutable, separates scratch work from final solve artifacts, and exposes the installed `ctf-skills` collection directly to Codex.

## Quick start

```powershell
# Verify project integrity quickly; add --wsl-tools for the 58-item Kali check
.\ctf.ps1 doctor --project-only
.\ctf.ps1 doctor --wsl-tools

# Enforce the exact locked skill tree and strict SKILL.md frontmatter
python scripts\check_skill_snapshot.py

# Create a challenge; keep the challenge page separate from the authorized target
.\ctf.ps1 new --event dreamhack-2026 --category web --name baby-sqli `
  --source-url https://ctf.example/challenges/1 --target-url https://target.example/

# Import immutable originals, verify them, then triage
.\ctf.ps1 import c\dreamhack-2026\web\baby-sqli C:\Downloads\challenge.zip
.\ctf.ps1 verify-input c\dreamhack-2026\web\baby-sqli
.\ctf.ps1 triage c\dreamhack-2026\web\baby-sqli

# Create an isolated parallel-agent notebook
.\ctf.ps1 agent-work c\dreamhack-2026\web\baby-sqli sqli-pass

# Reproduce the solver, store only a redacted proof, then record the flag locally
.\ctf.ps1 verify c\dreamhack-2026\web\baby-sqli --record

# List all challenge states
.\ctf.ps1 status
```

`triage` never writes or prints a plaintext candidate in tracked/scratch reports. It records only SHA-256 and UTF-8 length in `work/triage.json`; any plaintext candidate is kept in the ignored `.local/triage-candidates.json` store.

Open the generated challenge directory in Codex. Use `solve-challenge` when the category is uncertain, or invoke the matching `ctf-*` skill directly when it is known. Newly installed skills are detected automatically; restart Codex if they do not appear in the selector during the current session.

## Layout

```text
.agents/skills/   Project-scoped CTF skills
.ctf/             Workspace and skill-source metadata
c/                Challenges: c/<event>/<category>/<slug>
shared/           Reusable helpers, payloads, and snippets
templates/        Files copied into every new challenge
scripts/ctf.py    Dependency-free workspace CLI
scripts/check_skill_snapshot.py  Strict skill snapshot validator
scripts/install_ctf_tools.sh     Stable shim for the vendored tool installer
scripts/Install-CtfWsl.ps1       Repeatable Kali dependency/tool bootstrap with final verification
scripts/Invoke-CtfWsl.ps1        Run the workspace CLI in the Kali CTF venv
scripts/ctf-python-compat.txt    Python 3.13 compatibility overlay
scripts/solve_verification.py    Bounded solver runner and redacted proof writer
scripts/skill_source.py          Read-only source check and safe update staging
scripts/Test-Ctf.ps1             PowerShell 5.1 smoke test
ctf.ps1           PowerShell 5.1-compatible entrypoint
```

Each challenge contains:

```text
challenge.json    Machine-readable metadata and target scope
AGENTS.md          Challenge-local scope for Codex
README.md          Challenge description and quick commands
notes.md           Facts, hypotheses, and dead ends
input/             Original files; never edit in place
work/              Disposable experiments (Git-ignored)
solve/             Final reproducible solver/exploit
output/            Raw/generated output (Git-ignored)
evidence/          Small curated proof for the write-up
writeup.md         Final handoff after solving
```

The short `c/` root is intentional: Windows long-path support is currently disabled, and extracted CTF artifacts often have deeply nested names.

## Installed skills

The repository-local skills come from [daejaeLee/ctf-skills](https://github.com/daejaeLee/ctf-skills):

- `solve-challenge`
- `ctf-ai-ml`, `ctf-crypto`, `ctf-forensics`, `ctf-malware`
- `ctf-misc`, `ctf-osint`, `ctf-pwn`, `ctf-reverse`, `ctf-web`
- `ctf-writeup`

The snapshot is pinned to commit `36c72e53a96a035791821caff7440882ea0f5c57`. Source metadata and the expected tree digest are recorded in `.ctf/skills.lock.json`; per-file SHA-256 values for all 118 vendored skill files live in `.ctf/skills.manifest.json`. Support and project-authored files inside `.agents/skills/` are pinned separately in the lock.

Run `python scripts\check_skill_snapshot.py` for the authoritative strict check. It rejects unknown or missing skill directories and files, checksum changes, symlinks, unbounded top-level frontmatter, missing `name`/`description` fields, and duplicate names or top-level keys. Candidate update staging applies the same link and unexpected-skill rejection before it reports a snapshot as validated.

`.ctf/config.json` is the canonical place for category-to-skill routing and the default event/flag pattern used by the CLI.

Check the remote first, then clone and validate a candidate snapshot under the ignored `.cache/` directory. Staging never promotes or modifies `.agents/skills/`:

```powershell
.\ctf.ps1 skills-check --strict
.\ctf.ps1 skills-stage
```

Promotion is intentionally not automated because `.agents/skills/` is vendored. During an explicit maintenance update, replace only the locked skill directories and support files from the validated stage, preserve every `local_files` entry, then regenerate the integrity snapshot with:

```powershell
.\ctf.ps1 skills-manifest --commit <40-character-source-commit>
```

Update `.ctf/skills.lock.json` in the same change: move the old `resolved_commit` to `previous_commit`, set `resolved_commit` to the staged commit, update the skill list and support-file hashes when they changed, and copy the printed tree digest. A partial lock update is invalid by design.

Re-run the strict validator after updating lock metadata:

```powershell
python scripts\check_skill_snapshot.py
```

The upstream installer documents `scripts/install_ctf_tools.sh`. The repository-level shim makes that path stable, accepts options before or after one mode, applies the Python 3.13 compatibility overlay for `python`/`all`, and revalidates the required 58-item baseline if the vendored `all` mode reports an optional package failure. From Kali WSL:

```bash
bash scripts/install_ctf_tools.sh --verify
# Install only when required:
bash scripts/install_ctf_tools.sh all
```

For a fresh Kali WSL installation, the host-side bootstrap installs the required compilers and language runtimes as WSL root, runs the pinned installer in the correct user contexts, applies the small Python 3.13 compatibility overlay, and finishes with the 58-item verifier:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Install-CtfWsl.ps1
```

It does not read or persist a sudo password. SageMath is not part of the 58-item verifier and currently has no package candidate in the configured Kali snapshot, so the shim warns but permits a complete 58/58 baseline when SageMath is the remaining optional failure. Install SageMath in a challenge-local environment only when a crypto problem needs it.

When `solve/solve.py` needs pwntools, angr, or another Linux-only module, run the same CLI inside the Kali virtualenv (repository paths may use either `c\...` or `c/...`):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-CtfWsl.ps1 `
  verify c\dreamhack-2026\pwn\example --record
```

## Environment note

Git, Python 3.13, Node.js, Git LFS, and Kali WSL are the supported baseline. The dedicated Kali environment currently passes all 58 checks from the pinned tool verifier. Use `doctor --wsl-tools` to recheck Linux-first pwn, reverse, forensics, and malware tooling. Keep conflicting Python dependencies in challenge-local environments or `~/.ctf-tools/venv` instead of the Windows host installation.

Run the complete project smoke test with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-Ctf.ps1
```

Keep any remote repository private while a competition is active. Live flags and local credentials belong only under `.local/`, which Git ignores. Solvers should emit a candidate only on stdout; verification rejects an exact UTF-8/UTF-16/CP949 candidate persisted anywhere in the challenge outside immutable `input/` or `.local/`. It also binds the proof to metadata, the complete solve tree, inputs, and tracked/curated challenge files, contains descendant processes on Windows and Kali WSL, and time-bounds flag-regex evaluation. Tracked write-ups must redact the recovered value even when `ctf-writeup` would normally include it.
