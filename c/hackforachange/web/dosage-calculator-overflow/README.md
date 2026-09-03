# dosage-calculator-overflow

- Event: `hackforachange`
- Category: `web`
- Skill: `ctf-web`
- Source: https://www.hackforachange.org/practice
- Target: `https://hackforachangeruntime.vercel.app/`
- Status: `solved`

## Description

Trigger an integer overflow in a medical dosage calculator to uncover hidden
functionality. The runtime describes a legacy PharmaSafe calculator ported from
handheld hardware, whose old numeric assumptions no longer hold.

## Fast path

```powershell
# Obtain a fresh authenticated runtime launch URL through the Practice page.
python .\c\hackforachange\web\dosage-calculator-overflow\solve\solve.py `
  --launch-url '<fresh runtime URL>'
```

The solver prints the runtime candidate only to stdout. Submit it through the
authenticated Practice card, then refresh the page to verify account credit.
