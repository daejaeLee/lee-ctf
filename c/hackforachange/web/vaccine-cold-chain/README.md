# vaccine-cold-chain

- Event: `hackforachange`
- Category: `web`
- Skill: `ctf-web`
- Source: https://www.hackforachange.org/practice
- Target: `https://hackforachangeruntime.vercel.app/vaccine-cold-chain`
- Status: `new`

## Description

Paste the exact challenge description and hints here.

## Fast path

```powershell
# From the repository root
.\ctf.ps1 import c\hackforachange\web\vaccine-cold-chain <artifact-or-directory> [...]
.\ctf.ps1 verify-input c\hackforachange\web\vaccine-cold-chain
.\ctf.ps1 triage c\hackforachange\web\vaccine-cold-chain
# After solve/solve.py reproducibly prints one candidate
.\ctf.ps1 verify c\hackforachange\web\vaccine-cold-chain --record
```

Ask Codex to solve this directory with `ctf-web`. If the category is uncertain or the challenge crosses categories, start with `solve-challenge`.
