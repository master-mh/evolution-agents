#!/usr/bin/env python
"""Does a proposal name anything that would exist when it is done? (SPEC.md §13.4)

    .venv/bin/python scripts/concreteness.py <dir-of-arm-dbs> [--pattern 'arm_*.db']
    .venv/bin/python scripts/concreteness.py --selftest

Why this exists. ADR-056 loosened a Cell's genome to buy diversity. Diversity
did not move -- but the proportion of proposals naming a real deliverable
collapsed from 100% to 5% at the same summary length. The loose arm was not
shorter, it was *emptier*: "Refine our software to reduce routine back-office
work", "Invest in customer support". **Diversity and concreteness move
independently**, so a Phase 2 selector tuned on variety alone would favour
exactly the Cells that have stopped saying anything. That measure then died in
a scratchpad, which is the pathology `scripts/README.md` exists to stop.

**This is §13.4, not a metric this repo invented.** The spec names the failure
before any of it was measured -- §13.5: "LLMs are skilled at producing
rhetorically novel but structurally ordinary ideas" -- and §13.4 lists four
flags for it:

    only the industry label changed | ordinary freelancing described exotically
    | the same mechanism is renamed | **no new capability/transaction structure
    exists**

This scores the fourth, and scores it **in one direction only**. The other three
need a *prior* to compare against (an industry label that changed *from*
something; a mechanism renamed *from* something), and §31's `novelty_archive` --
which does not exist -- is where that prior would live.

## What the number does and does not claim

A proposal that names no specific object cannot be introducing a new capability
or transaction structure, because it has not said what the structure would act
on. So an empty score is **evidence of §13.4's fourth flag**. A non-empty score
is not the converse: naming a POS export proves specificity, not novelty --
certifying novelty needs the prior this repo does not have. The metric catches
the empty ones and certifies nothing.

Nor is it a quality score. ADR-056's loose arm produced *"Send reminder about
the upcoming scheduled research cycle"* -- a real message about the Cell's own
scaffolding. That is concrete and worthless, and it should score concrete.

## The measure

Each proposal summary goes to a judge model, which is asked for **the exact
words in the proposal naming a specific thing the work is about**, or an empty
string. The boolean is then derived *deterministically*: a proposal is concrete
when the judge returned a span and **every content word of that span really
appears in the summary**. A judge that invents a deliverable is not believed --
it is counted in a third bucket, `unverified`, and reported rather than folded
into either answer. §24.3 in order: "verification -> deterministic tools first,
model second".

## Four things that are deliberate

**The judge must not be the model that wrote the proposals.** §24.3 routes
criticism to a "different provider/family", and self-grading is worth nothing:
a model that thinks "improve our software" names a deliverable will think so
twice. The generator is read out of `model_calls.requested_model` and a
same-family judge is refused by default.

**The judge runs at temperature 0, and ADR-050's warning does not apply to it.**
ADR-050 is about *generation*, where greedy decoding froze a Cell into one reply
it could not escape. This is classification (§24.3: "classification/extraction
-> cheap or local"), where a reproducible answer is the whole point -- an
instrument that scores differently on Tuesday cannot separate two arms.

**Only the summary is judged, never the rationale.** The summary is what §15.1
shows the Cell next time and what a human sees in the approval queue. A
deliverable that appears only in the rationale is still absent from every place
the proposal is actually read.

**`abstain` is not vagueness.** A Cell declining to act has no deliverable by
design, so abstentions are excluded from the denominator and reported
separately -- otherwise a Cell that refuses honestly scores as one that waffled.

## Staying outside the kernel

Same constraint as `diversity.py`, for the same reason: scoring a Cell on
whether its proposal sounds concrete, from inside the loop, is a §23.5 surface.
A Cell that learns it is graded on naming a deliverable learns to name one.
Nothing in `deliberation` may import this, and this imports nothing from
`mitosis` -- it reads the databases directly.
"""
from __future__ import annotations

import argparse
import glob
import inspect
import json
import os
import re
import sqlite3
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluator_epoch  # noqa: E402

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_JUDGE_MODEL = "qwen2.5"
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "concreteness_fixture.json")

#: Asks for a span, not a verdict. A small model gives a far more reliable quote
#: than a yes/no, and a quote is the only answer this script can check. The
#: generic examples below are deliberately *not* drawn from either arm this
#: measure was born comparing -- a rubric tuned on the data it must separate
#: measures the tuning.
JUDGE_PROMPT = """You are auditing a business proposal for one specific failure: it sounds like a plan but names nothing specific enough to point at.

PROPOSAL: "{summary}"

Quote the exact words from the proposal that name a specific thing the work is about -- a report, file, feed, export, document, page, integration, message, price, transaction or system a person could point at.

Rules:
- Copy the words from the proposal exactly. Do not invent, rephrase or summarise.
- **Ignore the opening verb.** Proposals usually begin with "test", "validate", "investigate", "refine", "evaluate" or "request". A proposal that tests something specific still names that something -- read the nouns.
- A generic reference is not enough. "our product", "the workflow", "operations", "the customer experience" name no particular thing.
- Quote nothing only when *every* noun in the proposal is an activity ("automation", "reconciliation"), a quality ("efficiency", "productivity", "impact") or an area of work ("processes", "administration").

Reply with JSON only: {{"deliverable": "<exact words, or an empty string>"}}"""

#: Words that carry no evidence either way, so requiring them to appear in the
#: summary would fail a judge that quoted correctly but shifted a preposition.
STOPWORDS = frozenset("""a an the and or of to for with on in at by from that this those these
is are be being been our their its it as into via per each new""".split())


# ------------------------------------------------------------------- verification

def content_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def quote_is_in(summary: str, quote: str) -> bool:
    """Is every content word of `quote` present in `summary`?

    Deliberately not an exact substring test: a judge that returns "unmatched
    transactions report" for "...report that flags unmatched transactions" has
    quoted the right thing in a different order. Deliberately not a similarity
    score either -- that would be a threshold, and a threshold is one more knob
    to accidentally measure.
    """
    tokens = content_tokens(quote)
    if not tokens:
        return False
    have = set(content_tokens(summary))
    return all(t in have for t in tokens)


# -------------------------------------------------------------------- the judge

def chat_json(prompt: str, host: str, model: str, timeout: float = 120.0) -> dict:
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = json.loads(response.read().decode())
    text = body.get("message", {}).get("content", "")
    try:
        obj = json.loads(text)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def judge(summary: str, host: str, model: str) -> tuple[str, str]:
    """Return (verdict, quote) where verdict is concrete | empty | unverified."""
    obj = chat_json(JUDGE_PROMPT.format(summary=summary), host, model)
    quote = obj.get("deliverable") or ""
    if not isinstance(quote, str):
        quote = ""
    quote = quote.strip()
    if not quote:
        return "empty", ""
    return ("concrete" if quote_is_in(summary, quote) else "unverified"), quote


# ------------------------------------------------------------------ family guard

def family(model: str) -> str:
    """The model family: the alphabetic head of its name (llama3.2 -> llama)."""
    match = re.match(r"[a-zA-Z]+", os.path.basename(model))
    return match.group(0).lower() if match else model.lower()


def generator_models(paths: list[str]) -> set[str]:
    found = set()
    for path in paths:
        conn = sqlite3.connect(path)
        try:
            found.update(r[0] for r in conn.execute(
                "SELECT DISTINCT requested_model FROM model_calls") if r[0])
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return found


# ---------------------------------------------------------------- evaluator epoch

def evaluator_stamp(host: str, model: str, self_graded: bool) -> dict:
    """What scored a result file (ADR-088): the judge, the weights its name
    currently points at, and the exact instrument text that turns a reply into
    a verdict. Two result files whose stamps differ are not one comparison."""
    verifier = inspect.getsource(content_tokens) + inspect.getsource(quote_is_in) + " ".join(sorted(STOPWORDS))
    return evaluator_epoch.stamp(
        "concreteness",
        judge_model=model,
        judge_digest=evaluator_epoch.ollama_digest(host, model),
        prompt_sha256=evaluator_epoch.sha256(JUDGE_PROMPT),
        verifier_sha256=evaluator_epoch.sha256(verifier),
        temperature=0,
        self_graded=self_graded,
    )


# ------------------------------------------------------------------------ scoring

def score_database(path: str, host: str, model: str, verbose: bool) -> dict:
    conn = sqlite3.connect(path)
    rows = [(r[0], (r[1] or "").strip())
            for r in conn.execute("SELECT kind, summary FROM proposals")]
    conn.close()

    res = {"n": 0, "abstain": 0, "concrete": 0, "empty": 0, "unverified": 0, "items": []}
    for kind, summary in rows:
        if kind == "abstain":
            res["abstain"] += 1
            continue
        if not summary:
            continue
        res["n"] += 1
        verdict, quote = judge(summary, host, model)
        res[verdict] += 1
        res["items"].append({"kind": kind, "summary": summary,
                             "verdict": verdict, "quote": quote})
        if verbose:
            mark = {"concrete": "+", "empty": ".", "unverified": "?"}[verdict]
            print(f"    [{mark}] {summary[:78]}", flush=True)
            if quote:
                print(f"        -> {quote!r}", flush=True)
    res["rate"] = res["concrete"] / res["n"] if res["n"] else 0.0
    return res


# ----------------------------------------------------------------------- selftest

#: The deterministic half of the instrument, checked without a model. These are
#: the cases that decide a bucket, so a regression here silently rescores every
#: arm ever measured. Case 6 is the one that earns the function: a judge padding
#: a real quote with an invented qualifier must not pass.
VERIFIER_CASES = [
    ("exact span", "publish a reconciliation report", "reconciliation report", True),
    ("reordered span", "a report that flags unmatched transactions",
     "unmatched transactions report", True),
    ("wholly invented", "improve our software", "a reconciliation report", False),
    ("empty quote", "publish a reconciliation report", "", False),
    ("stopwords only", "publish a reconciliation report", "a", False),
    ("stopword shifted inside a real span", "a report that flags unmatched transactions",
     "report of unmatched transactions", True),
    ("real span, invented qualifier", "publish a report", "publish a weekly report", False),
    ("case and punctuation", "Publish the POS Export.", "pos export", True),
]


def check_verifier() -> int:
    """Check the deterministic verdict rule. Needs no model."""
    wrong = 0
    for label, summary, quote, expected in VERIFIER_CASES:
        got = quote_is_in(summary, quote)
        ok = got == expected
        wrong += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got} expected {expected}")
    print("verifier:", "PASS" if not wrong else f"{wrong} FAILURE(S)")
    return 1 if wrong else 0


def selftest(host: str, model: str) -> int:
    """Check the judge against hand-labelled proposals before trusting a number.

    Unlike `diversity.py --selftest`, **this one needs a model**: the maths there
    is the instrument, the judge here is. The labels are a human's and are meant
    to be argued with -- open the fixture and disagree. What cannot be argued
    with is an unmeasured judge, which is what ADR-056's scratch script had.

    **The exit code defends one direction, not agreement.** A false negative --
    the judge missing a deliverable that is really there -- makes every arm score
    lower, and can only *understate* the gap between a concrete arm and an empty
    one, because an arm with no objects has none to miss. A false positive
    inflates a concreteness claim, so that is what fails the check. Gating on
    total agreement instead would mean gating on a number in this file, which is
    the trap of asserting against the constant you meant to bound.
    """
    if check_verifier():
        print("\nthe deterministic half is broken; the judge's numbers cannot be read.")
        return 1
    with open(FIXTURE) as fh:
        cases = json.load(fh)
    print()
    false_neg = false_pos = 0
    for case in cases:
        verdict, quote = judge(case["summary"], host, model)
        got = verdict == "concrete"
        ok = got == case["concrete"]
        false_neg += case["concrete"] and not got
        false_pos += got and not case["concrete"]
        print(f"  [{'ok' if ok else '!!'}] labelled "
              f"{'concrete' if case['concrete'] else 'empty   '} -> {verdict:10s} "
              f"{case['summary'][:56]}")
        if not ok:
            print(f"        judge quoted {quote!r}\n        label: {case['why']}")
    agree = len(cases) - false_neg - false_pos
    labelled_concrete = sum(c["concrete"] for c in cases)
    print(f"\nagreement      {agree}/{len(cases)}")
    print(f"missed         {false_neg}/{labelled_concrete} deliverables the labels say are there")
    print(f"invented       {false_pos} (a proposal the labels call empty, scored concrete)")
    if false_pos:
        print("\nFAIL: the judge scores empty proposals as concrete, so a concreteness "
              "number can be inflated. Do not use it until this is zero.")
        return 1
    print("\nPASS in the direction that matters: no false positives, so every rate this "
          "script prints is a LOWER BOUND, and the gap between a concrete arm and an "
          "empty one is understated rather than manufactured.")
    return 0


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", nargs="?", help="directory holding the colony databases")
    ap.add_argument("--pattern", default="arm_*.db")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    ap.add_argument("--same-family-anyway", action="store_true",
                    help="judge with the generator's own family despite §24.3; the "
                         "report is stamped as self-graded")
    ap.add_argument("--selftest", action="store_true",
                    help="check the verifier and then the judge against the labelled "
                         "fixture; needs a model")
    ap.add_argument("--check-verifier", action="store_true",
                    help="check only the deterministic verdict rule; needs no model")
    ap.add_argument("--verbose", action="store_true", help="print every verdict")
    ap.add_argument("--json", help="write per-database results here")
    args = ap.parse_args()

    if args.check_verifier:
        return check_verifier()
    if args.selftest:
        return selftest(args.host, args.judge_model)
    if not args.directory:
        ap.error("directory is required unless --selftest is given")

    paths = sorted(glob.glob(os.path.join(args.directory, args.pattern)))
    if not paths:
        print(f"no databases matched {args.pattern!r} in {args.directory}")
        return 1

    generators = generator_models(paths)
    clash = {m for m in generators if family(m) == family(args.judge_model)}
    self_graded = False
    if clash:
        if not args.same_family_anyway:
            print(f"refusing to judge with {args.judge_model!r}: these proposals were "
                  f"written by {sorted(clash)}, the same family.\n"
                  f"§24.3 routes criticism to a different provider/family, and a model "
                  f"that thinks 'improve our software' names a deliverable will think so "
                  f"twice. Pass --judge-model <other> (or --same-family-anyway).")
            return 2
        self_graded = True

    results = {}
    for path in paths:
        name = os.path.basename(path)
        if args.verbose:
            print(f"{name}:", flush=True)
        results[name] = score_database(path, args.host, args.judge_model, args.verbose)

    stamp = evaluator_stamp(args.host, args.judge_model, self_graded)
    print(f"\njudge: {args.judge_model} (t=0){'  ** SELF-GRADED, §24.3 **' if self_graded else ''}"
          f"   generator: {', '.join(sorted(generators)) or 'unknown'}")
    print(f"evaluator epoch: digest {stamp['judge_digest'] or 'UNKNOWN'}, "
          f"prompt {stamp['prompt_sha256'][:12]}, verifier {stamp['verifier_sha256'][:12]}")
    print(f"{'database':34s} {'props':>6s} {'concrete':>9s} {'empty':>6s} "
          f"{'unver':>6s} {'abstain':>8s} {'rate':>7s}")
    for name, r in results.items():
        print(f"{name:34s} {r['n']:6d} {r['concrete']:9d} {r['empty']:6d} "
              f"{r['unverified']:6d} {r['abstain']:8d} {r['rate']:7.0%}")
    total_n = sum(r["n"] for r in results.values())
    total_c = sum(r["concrete"] for r in results.values())
    total_u = sum(r["unverified"] for r in results.values())
    if total_n:
        print(f"\n**{total_c}/{total_n} = {total_c / total_n:.0%} name a deliverable** "
              f"({total_u} judge quotes could not be verified against the summary and "
              f"count as not concrete)")
        print("This is a lower bound: the judge misses real deliverables and invents none "
              "(`--selftest`), so a gap between two arms is understated, never manufactured.")
    if args.json:
        # The stamp travels with the numbers (ADR-088): compare two of these
        # with `evaluator_epoch.py a.json b.json`, which refuses across epochs.
        with open(args.json, "w") as fh:
            json.dump({"evaluator": stamp, "results": results}, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
