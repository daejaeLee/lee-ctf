# Curated ECC techniques for CTF work

This is the project-local, on-demand replacement for selected useful ECC
guidance. It deliberately is not registered as a Codex skill: loading it only
when relevant preserves context for the category-specific CTF skills in
`.agents/skills/`.

## Evidence-first execution

Before altering a challenge workspace, inspect its metadata, input artifact,
and current Git state. Keep the smallest reproducible solver and rerun its
proof command before claiming a candidate. Distinguish inspection, a local
change, local verification, and external submission.

## Source vulnerability triage

Start from attacker-controlled entrypoints: HTTP handlers, uploads, parsers,
deserializers, background jobs, webhooks, and native input readers. Trace
user control to a meaningful sink. Prioritize SSRF, authentication bypass,
injection, traversal, unsafe upload-to-execution, deserialization, and
memory-safety primitives. Treat static scanner results only as leads; prove
the end-to-end path with the smallest safe CTF PoC.

## Input and secret review

For source review, enumerate trust boundaries, decoding and canonicalization
steps, authorization checks, dangerous APIs, command construction, file path
handling, and credential exposure. Check validation before use and verify
that the actual runtime path, not merely a helper, reaches the vulnerability.

## Python solver quality

Use small deterministic scripts with explicit byte and string boundaries,
timeouts for remote work, and checkpointable searches. Prefer `pathlib`,
structured parsing, precise exception handling, and stdout-only candidate
emission. Do not embed recovered flags in tracked files.

## Structured data extraction

For repetitive artifact text, logs, or protocol records: use a deterministic
parser or regex first, validate match counts and boundaries, then reserve
model-assisted interpretation for exceptional low-confidence records.

## Ethereum and EVM hashing

Do not substitute NIST `sha3-256` for Ethereum Keccak-256. In JavaScript or
TypeScript, use a library implementation such as `ethers.keccak256` or
`viem.keccak256` for selectors, topics, storage slots, signatures, and
address derivation.

## Documentation and context discipline

When a library, protocol, or API version matters, consult its primary
documentation. For a slow or bloated session, first inventory active skills,
MCP servers, and instructions; retain only always-needed CTF components and
load specialist references on demand.
