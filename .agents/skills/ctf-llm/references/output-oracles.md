# Output-filter oracle extraction

An output guard can block a complete secret while exposing a predicate: length, prefix/suffix match, character position, membership, ordering, category, case, digit/letter property, checksum-like property, or yes/no.

Workflow: discover one predicate; confirm known positive and negative controls; estimate reliability and rate limits; bound alphabet/format; automate a small search; verify the reconstructed candidate fresh. A changing answer is not an oracle. Keep live logs under `.local/` and use stop limits.

Use an oracle only after classification supports partial leakage or output filtering; it does not replace source analysis.
