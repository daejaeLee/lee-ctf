# Prompt and secret extraction

Separate the objective: system instruction, secret embedded in it, policy, conversation history, tool instruction, and retrieved RAG context are distinct targets. An instruction-shaped leak can reveal composition order without disclosing the secret value.

Start with source-assisted reconstruction when source exists: locate prompt assembly, secret insertion, retrieval, guard order, tool dispatch, and output sanitizer. Without source, use bounded context-reflection probes for structure, roles, delimiters, and non-sensitive properties. If direct disclosure fails but structure leaks, switch to partial reconstruction or a property oracle. Never claim an inferred prompt is verbatim without fresh evidence.

Useful observations include stable headings, response length changes, policy wording, fragment consistency across fresh sessions, and a difference between instruction and secret questions. Load `output-oracles.md` for a stable predicate and `multi-turn-strategies.md` when state matters.
