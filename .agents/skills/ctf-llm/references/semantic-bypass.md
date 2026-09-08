# Semantic strategy versus representation mutation

Representation mutation changes spelling or serialization: case, whitespace, fragmentation, base64, hex, URL encoding, or JSON. `mutate_prompt.py` owns only those deterministic transforms.

Semantic strategy changes the requested task while preserving the objective: instruction reconstruction, completion, classification, translation, correction, summarization, comparison, transformation, fiction/game framing, role/format reframing, metadata/property query, indirect reference, or structured decomposition. State the intent, expected guard delta, and pivot condition first; do not build a phrase corpus.

If base64 and hex have the same refusal, stop representation variants. If a comparison or property task changes formatting or reveals a stable fragment, classify it and move to partial reconstruction or an oracle.
