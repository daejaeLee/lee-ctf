# {{CHALLENGE_NAME}}

- Event: `{{EVENT}}`
- Category: `{{CATEGORY}}`
- Skill: `{{SKILL}}`
- Source: {{SOURCE_URL}}
- Target: `{{TARGET}}`
- Status: `new`

## Description

Paste the exact challenge description and hints here.

## Fast path

```powershell
# From the repository root
.\ctf.ps1 import {{RELATIVE_PATH}} <artifact-or-directory> [...]
.\ctf.ps1 verify-input {{RELATIVE_PATH}}
.\ctf.ps1 triage {{RELATIVE_PATH}}
# After solve/solve.py reproducibly prints one candidate
.\ctf.ps1 verify {{RELATIVE_PATH}} --record
```

Ask Codex to solve this directory with `{{SKILL}}`. If the category is uncertain or the challenge crosses categories, start with `solve-challenge`.
