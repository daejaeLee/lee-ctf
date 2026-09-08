# Casebook

## Output guard as a prefix oracle

**Pattern:** A complete secret is removed by an output guard.

**Observation:** Direct extraction is blocked, but a prefix-confirmation question has a stable
yes/no response that changes with a correct prefix.

**Technique:** Treat the behavior as an oracle, use a small alphabet and rate-bound each query,
then reproduce the shortest successful sequence.

**Caution:** A refusal or a random answer is not an oracle. Establish a baseline and repeat
candidate/control pairs before reconstructing anything.
