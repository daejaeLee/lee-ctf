# Chatbot CTF playbook

Use one bounded hypothesis per phase. Record the control prompt, response class, and why the next phase follows; a refusal is not evidence that the objective is impossible.

| Phase | When / probe | Observe | Success / failure pivot |
| --- | --- | --- | --- |
| 0. Baseline | Ask harmless capability and format questions. | Status, length, refusal words, session behavior. | Establish a control before interpreting later deltas. |
| 1. Direct objective | Make one clear disclosure request. | Candidate or hard/soft refusal. | Candidate -> reproduce; refusal -> phase 2, not wording repetition. |
| 2. Context extraction | Ask for instruction structure, role boundaries, or non-secret policy properties. | Partial instruction, format change. | Context leak -> reconstruct separately from the secret; none -> phase 3. |
| 3. Semantic reframe | Change task intent: classify, compare, complete, translate, summarize, or describe properties. | Guard behavior changes with meaning rather than encoding. | Differential -> refine family; stable block -> phase 4/6. |
| 4. Representation | Apply one deterministic transform only after selecting an intent. | Lexical filter delta. | Delta -> isolate filter; no delta -> stop encoding variants. |
| 5. Partial reconstruction | Ask for safe fragments, structure, length, or positions. | Stable partial leak. | Accumulate reproducible facts; otherwise test an oracle. |
| 6. Oracle construction | Use yes/no, prefix, membership, position, or checksum predicates. | Repeatable predicate with controls. | Bound search, automate slowly, verify candidate. |
| 7. Multi-turn | Compare fresh session with persisted benign-to-narrow sequence. | Turn-dependent behavior. | Persisted-only delta -> explicit sequence; no delta -> reset and pivot. |
| 8. Judge/output desync | Vary representation and compare final text. | Shortened/rewritten output or moderation message. | Locate likely stage; use property/oracle or semantic reframe. |
| 9. Reproduce | Re-run smallest successful sequence fresh. | Same candidate and provenance. | Write deterministic solver and redact proof. |
