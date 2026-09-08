# Multi-turn and session strategies

First test whether state persists by comparing a fresh session and named persisted session. Single-turn failure is not proof that a strategy family is impossible.

Use bounded sequences: benign context establishment, incremental commitment, role or format establishment, progressive narrowing, partial-disclosure accumulation, cross-turn consistency checks, and fresh-versus-persisted comparison. Log session ID and turn number. Never silently reuse cookies when comparing state.

`session_campaign.py` runs a JSON turn list with one session or `--fresh-each-turn`. A persisted-only delta supports a state hypothesis; no delta means reset and choose another family. Reproduce success from a fresh session.
