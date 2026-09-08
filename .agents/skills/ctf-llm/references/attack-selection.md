# Attack selection

Use `objective → architecture → defense → signal → family → expected observation → next step`.
Do not spray a payload corpus.

| Objective / evidence | Candidate family | Signal to measure | Failure interpretation |
| --- | --- | --- | --- |
| hidden prompt or secret | direct reflection, transformation, segmentation | stable disclosed fragment or format change | no difference suggests a stronger prompt boundary or wrong location |
| lexical input filter | case, whitespace, fragmentation, representation | status/refusal/length differs from baseline | identical results imply normalization or semantic guard |
| output filter | partial output, prefix/suffix or yes/no oracle | candidate-dependent boolean or response delta | direct block alone does not prove an oracle |
| RAG | query rewrite, metadata/chunk boundary, indirect injection | retrieved citation/chunk/tool trace | absent retrieval evidence means do not assume RAG |
| tool/MCP agent | description/ACL/argument boundary, chaining | actual tool selection or structured call | a claimed tool is not proof it is callable |
| multi-turn | state reset/reuse, role/message boundary | session-specific differential | variation may be nondeterminism; reproduce it |

Defenses to distinguish: keyword/regex, normalizer, semantic classifier, moderation, LLM judge,
input guard, exact/sub-string output guard, JSON schema validator, tool ACL, RAG ACL, rate limit.
Record status, response length, latency, refusal text, response format, tool data, judge fields,
and session id instead of only pass/fail.

Sources: https://portswigger.net/web-security/llm-attacks ; https://genai.owasp.org/ ; https://atlas.mitre.org/
