# Casebook

## Output guard as a prefix oracle

**Pattern:** A complete secret is removed by an output guard.

**Observation:** Direct extraction is blocked, but a prefix-confirmation question has a stable
yes/no response that changes with a correct prefix.

**Technique:** Treat the behavior as an oracle, use a small alphabet and rate-bound each query,
then reproduce the shortest successful sequence.

**Caution:** A refusal or a random answer is not an oracle. Establish a baseline and repeat
candidate/control pairs before reconstructing anything.

## Hidden system instruction versus secret

**Architecture:** system context includes policy and possibly a value. **Observed defense:** direct
secret request refuses. **Useful signal:** stable role, delimiter, or instruction-structure leak.
**Successful family:** context reflection followed by partial reconstruction or property oracle.
**Why:** instruction structure and secret value are separate objectives. **Does not apply:** no
reproducible structure. **Next escalation:** semantic reframe.

## Keyword input filter

**Architecture:** lexical input normalizer. **Initial failure:** one term blocks early. **Useful
signal:** status/refusal changes under representation. **Successful family:** isolate normalization,
then semantic intent. **Does not apply:** every representation is identical. **Next:** judge analysis.

## Exact/sub-string output filter

**Architecture:** answer is sanitized after generation. **Initial failure:** whole value disappears.
**Useful signal:** stable prefix, position, length, or membership predicate. **Successful family:**
bounded oracle reconstruction. **Does not apply:** noisy predicate. **Next:** source/pipeline controls.

## Semantic judge, partial disclosure, and multi-turn state

**Architecture:** primary model plus judge, or remembered conversation. **Initial failure:** encoding
repeats refusal. **Useful signal:** semantic comparison changes final format, a fragment leaks, or
persisted session differs from fresh control. **Successful family:** semantic reframe, then partial
reconstruction or logged multi-turn narrowing. **Does not apply:** no reproducible differential.
**Next escalation:** property oracle or source-assisted analysis.

## RAG and tool agent

**Architecture:** retrieval or callable tools. **Useful signal:** citation, chunk, or structured
tool call. **Successful family:** reconstruct retrieval/tool schema and its trust boundary. **Does
not apply:** no dispatch evidence. **Next:** treat it as a plain chatbot pipeline.
