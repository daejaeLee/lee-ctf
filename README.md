# lee-ctf

Fast, reproducible workspace for authorized CTF challenges. The project keeps original inputs immutable, separates scratch work from final solve artifacts, and exposes the installed `ctf-skills` collection directly to Codex.

## Quick start

```powershell
# Verify the workspace and local tool availability
.\ctf.ps1 doctor

# Create a challenge (event names should include the year when useful)
.\ctf.ps1 new --event dreamhack-2026 --category web --name baby-sqli --url https://example.invalid

# Copy challenge files into the generated input\ directory, then triage
.\ctf.ps1 triage c\dreamhack-2026\web\baby-sqli

# List all challenge states
.\ctf.ps1 status
```

Open the generated challenge directory in Codex. Use `solve-challenge` when the category is uncertain, or invoke the matching `ctf-*` skill directly when it is known. Newly installed skills are detected automatically; restart Codex if they do not appear in the selector during the current session.

## Layout

```text
.agents/skills/   Project-scoped CTF skills
.ctf/             Workspace and skill-source metadata
c/                Challenges: c/<event>/<category>/<slug>
shared/           Reusable helpers, payloads, and snippets
templates/        Files copied into every new challenge
scripts/ctf.py    Dependency-free workspace CLI
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

The snapshot is pinned to commit `36c72e53a96a035791821caff7440882ea0f5c57`. Source metadata and the expected tree digest are recorded in `.ctf/skills.lock.json`; per-file SHA-256 values for all 118 vendored skill files live in `.ctf/skills.manifest.json`. `doctor` checks both, so modified, missing, or extra skill files fail loudly.

`.ctf/config.json` is the canonical place for category-to-skill routing and the default event/flag pattern used by the CLI. After an intentional skill update, regenerate the integrity snapshot with:

```powershell
.\ctf.ps1 skills-manifest --commit <40-character-source-commit>
```

Then copy the printed tree digest into `.ctf/skills.lock.json` and run `.\ctf.ps1 doctor`.

## Environment note

Git, Python 3.13, Node.js, Git LFS, and Kali WSL are present. The current managed session cannot start WSL, and the Windows host does not yet have the main pwn/reversing toolchain. Use `doctor` to distinguish missing tools from an installed-but-blocked WSL service. Toolchain installation is intentionally a separate phase so the project scaffold remains reproducible.

Keep any remote repository private while a competition is active. Flags and local credentials belong under `.local/`, which Git ignores.
