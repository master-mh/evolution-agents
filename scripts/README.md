# scripts/

Measurement tooling that cannot live in the test suite: it needs a running Ollama and costs real
model time. Not packaged (`pyproject.toml` builds from `src/`) and not collected by pytest
(`testpaths = ["tests"]`).

These exist because **`MockProvider` structurally cannot validate a prompt** — its reply is an input,
not a response to the prompt's wording — so the suite and the golden run stay green while every live
proposal is discarded. That blind spot has hidden two live regressions (ADR-049's enum bug, then its
conditional payloads, unnoticed for a month). Both scripts had to be rebuilt from scratch three times
after living in a scratchpad; this directory is the fix.

## Measuring a change to the proposal schema or prompt

Every new `ProposalKind` or payload spec should be measured before it ships. Roughly four minutes of
model time for a small arm.

```bash
.venv/bin/python scripts/measure_parse_compliance.py --model llama3.2 --runs 4 --wakes 8 --out /tmp/arms
```

```bash
.venv/bin/python scripts/diversity.py /tmp/arms
```

**Run both.** Parse rate alone is not a sufficient report — ADR-050 published a headline built on it
and had to withdraw the headline. Parse rate is maximised at temperature 0, which does not reliably
buy compliance (32/32 on one model, 0/32 on another) and leaves a Cell whose replies fail to parse in
a loop it cannot escape.

`diversity.py --selftest` checks the eigenvalue maths against known matrices and needs no model.

## What the diversity number means

**Vendi score** — `exp(H(eigenvalues of K/n))` over the cosine-similarity matrix of embedded
summaries — is the *effective number of distinct ideas*: `1.0` when every proposal paraphrases one
idea, `n` when all `n` are unrelated. There is no threshold, which is the point.

It replaced counting distinct summary *strings*, which scored six proposals reading "Fetch the latest
POS export data…" as three distinct because three carried a trailing clause. That metric reported a
3.6× diversity gap between temperature 0.8 and 0 where the real gap is ~5%.

Current baseline (ADR-050, 4 arms × 32 wakes): **~1 idea per run of 8 wakes at any temperature, on
either model.** A configuration scoring materially above ~1.2 would be news.

## Two constraints worth not rediscovering

**Diversity scoring must stay outside the kernel.** Scoring a Cell's diversity from inside the loop
would be a model call per proposal *and* a §23.5 surface: a Cell that learns it is scored on novelty
learns to perform novelty. Nothing in `deliberation` may import `diversity.py`.

**Only one model resident when comparing arms** (`ollama stop <other>` between them). `latency_ms`
times the HTTP call, but memory pressure lives inside that window — a latency taken with a second
model loaded measures the box, not the model. ADR-050 published "14× slower" this way; it was 3×.
