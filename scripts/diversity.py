#!/usr/bin/env python
"""Semantic diversity of recorded proposals — the effective number of distinct ideas.

    .venv/bin/python scripts/diversity.py <dir-of-arm-dbs> [--pattern 'arm_*.db']
    .venv/bin/python scripts/diversity.py --selftest

Why this exists (ADR-050, third correction). Diversity was first measured as
*distinct summary strings*, which counts two rewordings of one idea as two
proposals. That metric produced ADR-050's headline and the headline was wrong:
it reported a 3.6x diversity gap between temperature 0.8 and 0 where the real
gap is ~5%. Six proposals reading "Fetch the latest POS export data..." scored
3 distinct because three carried a trailing clause.

The measure. Each proposal's summary is embedded, and the run is scored by
**Vendi score** -- exp(H(eigenvalues of K/n)) over the cosine-similarity matrix
K. It is the *effective number of distinct items*: 1.0 when every proposal
paraphrases one idea, n when all n are unrelated. There is no threshold to
tune, which is the point -- a threshold is one more knob to accidentally
measure. `--tau` clustering is reported only as a cross-check.

**This is analysis instrumentation and must stay outside the kernel.** Scoring a
Cell's diversity from inside the loop would be a model call per proposal and a
§23.5 surface: a Cell that learns it is scored on novelty learns to perform
novelty. Nothing in `deliberation` may import this.

No numpy on purpose. The eigenproblem is symmetric and tiny (one run of wakes),
and adding a dependency to the project venv for an analysis script is not a
trade this repo makes. Jacobi rotation is exact at this size; `--selftest`
checks it against known matrices and needs no model.
"""
from __future__ import annotations

import argparse
import glob
import json
import itertools
import math
import os
import random
import inspect
import sqlite3
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluator_epoch  # noqa: E402

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_EMBED_MODEL = "nomic-embed-text"


# --------------------------------------------------------------------------- math

def unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine_matrix(vectors: list[list[float]]) -> list[list[float]]:
    vs = [unit(v) for v in vectors]
    return [[sum(a * b for a, b in zip(u, w)) for w in vs] for u in vs]


def jacobi_eigenvalues(mat, iters: int = 100, tol: float = 1e-12) -> list[float]:
    """Eigenvalues of a symmetric matrix by cyclic Jacobi rotation."""
    n = len(mat)
    a = [row[:] for row in mat]
    for _ in range(iters):
        off = math.sqrt(sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j))
        if off < tol:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) < tol:
                    continue
                theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
                t = (1 if theta >= 0 else -1) / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
    return [a[i][i] for i in range(n)]


def vendi_score(sims) -> float:
    """Effective number of distinct items in a similarity matrix."""
    n = len(sims)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0
    ev = [max(e, 0.0) for e in jacobi_eigenvalues([[v / n for v in row] for row in sims])]
    total = sum(ev) or 1.0
    ev = [e / total for e in ev]
    return math.exp(-sum(e * math.log(e) for e in ev if e > 1e-12))


def vendi_at(sims, k: int, cap: int = 400, seed: int = 0) -> float | None:
    """Mean Vendi score over subsets of size `k` -- the matched-n comparison.

    Vendi is bounded above by n, so an arm that produced 4.5 proposals per run
    cannot be compared with one that produced 1.75 by their raw scores: the
    difference would be mostly the count. Fixing the subset size removes that.
    ADR-056 and ADR-058 both rest on `ideas@2`, and until ADR-058 it existed in
    neither script -- the same way ADR-056's concreteness measure did not.

    Exact over all C(n, k) subsets while that is small; beyond `cap`, a seeded
    random sample of them, so the number stays reproducible.
    """
    n = len(sims)
    if n < k:
        return None
    idx = range(n)
    subsets = list(itertools.combinations(idx, k))
    if len(subsets) > cap:
        subsets = random.Random(seed).sample(subsets, cap)
    total = 0.0
    for sub in subsets:
        total += vendi_score([[sims[i][j] for j in sub] for i in sub])
    return total / len(subsets)


def greedy_clusters(sims, tau: float) -> int:
    n = len(sims)
    seen = [False] * n
    k = 0
    for i in range(n):
        if seen[i]:
            continue
        k += 1
        seen[i] = True
        for j in range(i + 1, n):
            if not seen[j] and sims[i][j] >= tau:
                seen[j] = True
    return k


# ---------------------------------------------------------------------- embedding

def embed(texts: list[str], host: str, model: str) -> list[list[float]]:
    req = urllib.request.Request(
        f"{host}/api/embed",
        data=json.dumps({"model": model, "input": texts}).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode())["embeddings"]


# ----------------------------------------------------------------------- selftest

def selftest() -> int:
    """Check the eigenvalue path against matrices whose Vendi score is known.

    Needs no model: these are the similarity matrices an embedder would produce
    in the limiting cases, so a regression in the maths is caught without one.
    """
    cases = [
        ("4 identical items", [[1.0] * 4 for _ in range(4)], 1.0, 1e-6),
        ("4 mutually orthogonal items",
         [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)], 4.0, 1e-6),
        ("2 identical + 2 identical, the pairs unrelated",
         [[1.0, 1.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0],
          [0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0]], 2.0, 1e-6),
    ]
    failures = 0
    for label, K, expected, tol in cases:
        got = vendi_score(K)
        ok = abs(got - expected) < tol
        failures += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}: vendi={got:.6f} expected={expected}")

    #: `vendi_at` is the number arms are actually compared with, so it gets its
    #: own cases. The third is the one that earns them: ideas@2 over two
    #: identical pairs is 10/6, not 2 -- a third of the pairs are within a pair.
    at_cases = [
        ("ideas@2 of 4 identical items", [[1.0] * 4 for _ in range(4)], 2, 1.0),
        ("ideas@2 of 4 orthogonal items",
         [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)], 2, 2.0),
        ("ideas@2 of 2 identical + 2 identical",
         [[1.0, 1.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0],
          [0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0]], 2, 10 / 6),
        ("ideas@3 asked of a 2-item matrix is undefined",
         [[1.0, 0.0], [0.0, 1.0]], 3, None),
    ]
    for label, K, k, expected in at_cases:
        got = vendi_at(K, k)
        ok = (got is None and expected is None) or (
            got is not None and expected is not None and abs(got - expected) < 1e-6)
        failures += not ok
        shown = "None" if got is None else f"{got:.6f}"
        print(f"  [{'ok' if ok else 'FAIL'}] {label}: {shown} expected={expected}")

    print("selftest:", "PASS" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


# ---------------------------------------------------------------- evaluator epoch

def evaluator_stamp(host: str, model: str, tau: float, at: int | None) -> dict:
    """What scored a result file (ADR-088): the embedding model, the weights
    its name currently points at, the scoring code, and the two settings that
    change the headline number."""
    scoring = "".join(inspect.getsource(fn) for fn in (cosine_matrix, vendi_score, vendi_at))
    return evaluator_epoch.stamp(
        "diversity",
        embed_model=model,
        embed_digest=evaluator_epoch.ollama_digest(host, model),
        scoring_sha256=evaluator_epoch.sha256(scoring),
        tau=tau,
        at=at,
    )


# --------------------------------------------------------------------------- main

def score_directory(directory: str, pattern: str, host: str, model: str, tau: float,
                   at: int | None = None) -> dict:
    out = {}
    for path in sorted(glob.glob(os.path.join(directory, pattern))):
        conn = sqlite3.connect(path)
        summaries = [r[0].strip() for r in conn.execute("SELECT summary FROM proposals")]
        conn.close()
        name = os.path.basename(path)
        if not summaries:
            out[name] = {"n": 0, "strings": 0, "vendi": 0.0, "clusters": 0, "at": None}
            continue
        strings = len({s.lower() for s in summaries})
        at_k = None
        if len(summaries) == 1:
            vendi, clusters = 1.0, 1
        else:
            K = cosine_matrix(embed(summaries, host, model))
            vendi, clusters = vendi_score(K), greedy_clusters(K, tau)
            if at:
                got = vendi_at(K, at)
                at_k = round(got, 3) if got is not None else None
        out[name] = {"n": len(summaries), "strings": strings,
                     "vendi": round(vendi, 3), "clusters": clusters, "at": at_k}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", nargs="?", help="directory holding the colony databases")
    ap.add_argument("--pattern", default="arm_*.db")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    ap.add_argument("--tau", type=float, default=0.85, help="cross-check clustering threshold")
    ap.add_argument("--at", type=int, metavar="K",
                    help="also report ideas@K: the mean score over subsets of K proposals. "
                         "**Use this to compare arms** -- a raw score is bounded by how many "
                         "proposals an arm produced, so two arms with different parse rates "
                         "cannot be compared without it")
    ap.add_argument("--selftest", action="store_true", help="check the maths; needs no model")
    ap.add_argument("--json", help="write per-database results here")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.directory:
        ap.error("directory is required unless --selftest is given")

    results = score_directory(args.directory, args.pattern, args.host,
                              args.embed_model, args.tau, args.at)
    if not results:
        print(f"no databases matched {args.pattern!r} in {args.directory}")
        return 1

    at_col = f"ideas@{args.at}" if args.at else ""
    print(f"{'database':34s} {'props':>6s} {'strings':>8s} {'ideas (vendi)':>14s} "
          f"{'clust':>6s} {at_col:>9s}")
    for name, r in results.items():
        at = f"{r['at']:9.3f}" if r.get("at") is not None else " " * 9
        print(f"{name:34s} {r['n']:6d} {r['strings']:8d} {r['vendi']:14.3f} "
              f"{r['clusters']:6d} {at}")
    scored = [r for r in results.values() if r["n"]]
    if scored:
        print(f"\nmean over {len(scored)} scored databases: "
              f"{sum(r['n'] for r in scored) / len(scored):.2f} proposals, "
              f"**{sum(r['vendi'] for r in scored) / len(scored):.3f} ideas**, "
              f"{sum(r['strings'] for r in scored) / len(scored):.2f} distinct strings")
        at_runs = [r["at"] for r in scored if r.get("at") is not None]
        if at_runs:
            mean = sum(at_runs) / len(at_runs)
            var = sum((x - mean) ** 2 for x in at_runs) / (len(at_runs) - 1) if len(at_runs) > 1 else 0.0
            print(f"**ideas@{args.at} = {mean:.3f} +/- {math.sqrt(var / len(at_runs)):.3f}** "
                  f"over {len(at_runs)} databases with at least {args.at} proposals "
                  f"-- this is the number to compare arms with")
    if args.json:
        # The stamp travels with the numbers (ADR-088): compare two of these
        # with `evaluator_epoch.py a.json b.json`, which refuses across epochs.
        stamp = evaluator_stamp(args.host, args.embed_model, args.tau, args.at)
        with open(args.json, "w") as fh:
            json.dump({"evaluator": stamp, "results": results}, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
