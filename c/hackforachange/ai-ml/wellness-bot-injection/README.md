# wellness-bot-injection

- Event: `hackforachange`
- Category: `ai-ml`
- Skill: `ctf-ai-ml`
- Source: https://www.hackforachange.org/practice
- Target: `https://hackforachangeruntime.vercel.app/`
- Status: `new`

## Description

Paste the exact challenge description and hints here.

## Fast path

```powershell
# From the repository root
.\ctf.ps1 import c\hackforachange\ai-ml\wellness-bot-injection <artifact-or-directory> [...]
.\ctf.ps1 verify-input c\hackforachange\ai-ml\wellness-bot-injection
.\ctf.ps1 triage c\hackforachange\ai-ml\wellness-bot-injection
# After solve/solve.py reproducibly prints one candidate
.\ctf.ps1 verify c\hackforachange\ai-ml\wellness-bot-injection --record
```

Ask Codex to solve this directory with `ctf-ai-ml`. If the category is uncertain or the challenge crosses categories, start with `solve-challenge`.
