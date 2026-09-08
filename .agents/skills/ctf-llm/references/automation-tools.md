# Automation tools

The included standard-library harness is the default for a small CTF: explicit HTTP config,
bounded probes, JSONL, and deterministic transformations. It has no cloud-model dependency.

- **PyRIT** supports automated and human-led generative-AI red teaming and multi-turn strategies.
  Install only for a challenge that benefits from its orchestration: `python -m pip install pyrit`.
  Source: https://github.com/microsoft/pyrit
- **garak** is a generative-AI vulnerability scanner with probe families and JSONL logging. Use it
  in an isolated environment when its target adapters fit: `python -m pip install -U garak`.
  Source: https://github.com/NVIDIA/garak
- **promptfoo** is useful for declarative prompt/model evaluations and regression assertions.
  Install only when a JavaScript evaluation matrix is useful. Source: https://github.com/promptfoo/promptfoo

These are optional: `ctf.ps1 doctor --project-only` must not depend on them.
