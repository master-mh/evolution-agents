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
import math
import os
import sqlite3
import urllib.request

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
    print("selftest:", "PASS" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


# --------------------------------------------------------------------------- main

def score_directory(directory: str, pattern: str, host: str, model: str, tau: float) -> dict:
    out = {}
    for path in sorted(glob.glob(os.path.join(directory, pattern))):
        conn = sqlite3.connect(path)
        summaries = [r[0].strip() for r in conn.execute("SELECT summary FROM proposals")]
        conn.close()
        name = os.path.basename(path)
        if not summaries:
            out[name] = {"n": 0, "strings": 0, "vendi": 0.0, "clusters": 0}
            continue
        strings = len({s.lower() for s in summaries})
        if len(summaries) == 1:
            vendi, clusters = 1.0, 1
        else:
            K = cosine_matrix(embed(summaries, host, model))
            vendi, clusters = vendi_score(K), greedy_clusters(K, tau)
        out[name] = {"n": len(summaries), "strings": strings,
                     "vendi": round(vendi, 3), "clusters": clusters}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", nargs="?", help="directory holding the colony databases")
    ap.add_argument("--pattern", default="arm_*.db")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    ap.add_argument("--tau", type=float, default=0.85, help="cross-check clustering threshold")
    ap.add_argument("--selftest", action="store_true", help="check the maths; needs no model")
    ap.add_argument("--json", help="write per-database results here")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.directory:
        ap.error("directory is required unless --selftest is given")

    results = score_directory(args.directory, args.pattern, args.host,
                              args.embed_model, args.tau)
    if not results:
        print(f"no databases matched {args.pattern!r} in {args.directory}")
        return 1

    print(f"{'database':34s} {'props':>6s} {'strings':>8s} {'ideas (vendi)':>14s} {'clust':>6s}")
    for name, r in results.items():
        print(f"{name:34s} {r['n']:6d} {r['strings']:8d} {r['vendi']:14.3f} {r['clusters']:6d}")
    scored = [r for r in results.values() if r["n"]]
    if scored:
        print(f"\nmean over {len(scored)} scored databases: "
              f"{sum(r['n'] for r in scored) / len(scored):.2f} proposals, "
              f"**{sum(r['vendi'] for r in scored) / len(scored):.3f} ideas**, "
              f"{sum(r['strings'] for r in scored) / len(scored):.2f} distinct strings")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
