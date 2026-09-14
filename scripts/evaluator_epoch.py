#!/usr/bin/env python
"""Which evaluator produced a number, and may two numbers be compared? (SPEC.md
§24.2, §14.2; ADR-088)

    .venv/bin/python scripts/evaluator_epoch.py a.json b.json
    .venv/bin/python scripts/evaluator_epoch.py --selftest

Why this exists. `concreteness.py` and `diversity.py` are evaluators: a judge
model with a prompt and a verifier, an embedding model with a threshold. Every
ADR that compares two arms compares numbers those evaluators produced on
different days -- and until now a result file recorded *what* was scored and
nothing about *what scored it*. Two things can change underneath a comparison
without anyone deciding to change it:

- **The model behind a name.** `ollama pull qwen2.5` replaces the weights the
  name points at. §24.2: "a silent model update can change … reasoning
  quality. Treat material model changes as environment regime changes."
- **The instrument's own text.** A reworded judge prompt or a changed stopword
  list rescores every arm ever measured (`concreteness.py`'s own warning about
  its verifier cases).

The Red Queen Gödel Machine (arXiv 2606.26294) makes the rule explicit for
self-improving systems whose evaluators change: criteria stay **fixed within an
epoch**, and utility records from a displaced evaluator are erased rather than
compared across the boundary. SPEC.md §0.2 puts the evaluator in the immutable
kernel column, so evaluators here are never evolved by Cells at all -- but an
operator upgrading a judge is still an epoch boundary, and a comparison that
crosses one is not the comparison it names.

So each instrument's `--json` output now carries an `evaluator` stamp (model
name, the model's content digest where the host reports one, and SHA-256 of the
instrument text that decides a verdict), and this script refuses to compare two
result files whose stamps differ -- printing exactly which fields differ.

Imports nothing from `mitosis`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request

#: Fields that identify an evaluator but may legitimately differ between two
#: comparable runs: none today. Named so that adding one is a visible decision.
IGNORED_STAMP_FIELDS: frozenset[str] = frozenset()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ollama_digest(host: str, model: str, timeout: float = 10.0) -> str | None:
    """The content digest of the weights `model` currently names on `host`, or
    `None` if the host cannot say. A bare name means its `:latest` tag, the
    same resolution Ollama itself applies."""
    wanted = model if ":" in model else f"{model}:latest"
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as response:
            body = json.loads(response.read().decode())
    except (OSError, ValueError):
        return None
    for entry in body.get("models", []):
        if entry.get("name") == wanted or entry.get("model") == wanted:
            return entry.get("digest")
    return None


def stamp(instrument: str, **fields) -> dict:
    return {"instrument": instrument, **fields}


def stamp_differences(a: dict | None, b: dict | None) -> list[str]:
    """Human-readable reasons two stamps are not the same evaluator epoch.
    Empty means comparable. A missing stamp is itself a difference: a result
    that cannot say what scored it cannot be shown to match anything."""
    if not a or not b:
        return ["one or both results carry no evaluator stamp (written before ADR-088)"]
    reasons = []
    for key in sorted((set(a) | set(b)) - IGNORED_STAMP_FIELDS):
        if key not in a or key not in b:
            reasons.append(f"{key}: present in only one stamp")
        elif a[key] is None or b[key] is None:
            # An unknown digest is not a match: it might be the same weights,
            # and it might not, and the whole point is not to guess.
            reasons.append(f"{key}: unknown in at least one stamp ({a[key]!r} vs {b[key]!r})")
        elif a[key] != b[key]:
            reasons.append(f"{key}: {a[key]!r} vs {b[key]!r}")
    return reasons


def selftest() -> int:
    failures = 0

    def check(label, got, expected):
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}")

    base = stamp("concreteness", judge_model="qwen2.5", judge_digest="abc", prompt_sha256="p")
    check("identical stamps are comparable", stamp_differences(base, dict(base)), [])
    check("re-pulled weights under the same name are not",
          len(stamp_differences(base, {**base, "judge_digest": "def"})), 1)
    check("a reworded prompt is not", len(stamp_differences(base, {**base, "prompt_sha256": "q"})), 1)
    check("an unknown digest is not a match",
          len(stamp_differences(base, {**base, "judge_digest": None})), 1)
    check("a result with no stamp cannot be matched", len(stamp_differences(base, None)), 1)
    check("a field present on one side only is a difference",
          len(stamp_differences(base, {**base, "tau": 0.85})), 1)
    print("selftest:", "PASS" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", nargs="*", help="two --json result files from the same instrument")
    ap.add_argument("--selftest", action="store_true", help="needs no model")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if len(args.results) != 2:
        ap.error("give exactly two result files")

    loaded = []
    for path in args.results:
        with open(path) as fh:
            loaded.append(json.load(fh))
    stamps = [item.get("evaluator") if isinstance(item, dict) else None for item in loaded]
    reasons = stamp_differences(stamps[0], stamps[1])
    if reasons:
        print("refusing to compare: these results come from different evaluator epochs "
              "(§24.2; ADR-088)")
        for reason in reasons:
            print(f"  - {reason}")
        return 2
    print(f"comparable: same evaluator epoch ({stamps[0]['instrument']})")
    for key, value in sorted(stamps[0].items()):
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
