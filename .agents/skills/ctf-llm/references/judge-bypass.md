# Guard and judge topology

Model the pipeline rather than a monolithic filter:

```text
user -> input guard -> primary LLM -> output guard -> judge/moderation -> validator -> response
```

Control probes locate a likely block: early HTTP block suggests input guard; normal-looking content replaced with policy text suggests output guard or judge; schema errors suggest validator. Label these likely, possible, or unknown.

Compare semantic-equivalent requests and representations separately. Lexical-only change suggests normalization; meaning-only change suggests semantic reframe; stable partial content removed at final stage supports property/oracle reconstruction. Do not repeat direct disclosure after a stable hard refusal.
