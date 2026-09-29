"""Phase 3 - evaluation of entity resolution against hand-labelled name pairs.

    python -m ownership.er_eval sample    # draw the 100 pairs (refuses to overwrite a labelled file)
    python -m ownership.er_eval           # score the resolver, write data/er_evaluation.json

Sampling. A pair is two distinct filed names (holder or held) that
  - normalise differently in Phase 2 (pairs Phase 2 already makes identical
    are resolved by construction, so including them would only inflate the
    score), and
  - share at least one informative token: 3+ characters and appearing in at
    most 10 distinct names ("trust", "fund", "and", "india" do not count).
The pool is split into four bands by token overlap (Jaccard of the Phase 2
token sets: <0.25, 0.25-0.5, 0.5-0.75, >=0.75) and 25 pairs are drawn from
each with a fixed seed. Banding keeps both likely matches and hard
non-matches in the sample instead of a sample that is almost all easy
negatives.

Each pair is labelled by hand in data/er_validation_pairs.csv (same_entity =
1 or 0, rules in docs/entity_resolution.md). The resolver predicts "same" when
both names get the same entity ID.
"""
import csv
import json
import random
import sys
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from .ingest import read_records
from .normalise import normalise_name, tokens
from .resolve import CANDIDATE_RADIUS, _observations, build_index, token_match
from .similarity import levenshtein
from .trie import Trie

ROOT = Path(__file__).resolve().parent.parent
PAIRS = ROOT / "data" / "er_validation_pairs.csv"
SEED = 2026
PER_BAND = 25
BANDS = ("<0.25", "0.25-0.5", "0.5-0.75", ">=0.75")


def _names(records):
    return sorted({r.holder_name for r in records} | {r.held_name for r in records})


def candidate_pool(records):
    names = _names(records)
    toks = {n: set(tokens(n)) for n in names}
    df = Counter(t for s in {frozenset(v) for v in toks.values()} for t in s)
    pool = {b: [] for b in BANDS}
    for a, b in combinations(names, 2):
        if normalise_name(a) == normalise_name(b):
            continue
        shared = toks[a] & toks[b]
        if not any(len(t) >= 3 and df[t] <= 10 for t in shared):
            continue
        jaccard = len(shared) / len(toks[a] | toks[b])
        pool[BANDS[min(3, int(jaccard * 4))]].append((a, b))
    return pool


def sample(records, per_band=PER_BAND, seed=SEED):
    rng = random.Random(seed)
    out = []
    for band, pairs in candidate_pool(records).items():
        for a, b in rng.sample(pairs, min(per_band, len(pairs))):
            out.append({"name_a": a, "name_b": b, "band": band, "same_entity": "", "note": ""})
    return out


def load_pairs(path=PAIRS):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    unlabelled = [i + 2 for i, r in enumerate(rows) if r["same_entity"] not in ("0", "1")]
    if unlabelled:
        raise ValueError(f"{path.name}: rows without a 0/1 label on lines {unlabelled}")
    return rows


def score(pairs, index):
    """Confusion counts and precision / recall / F1 of `index` on labelled pairs."""
    tp = fp = fn = tn = 0
    errors = []
    for p in pairs:
        truth = p["same_entity"] == "1"
        pred = index.entity_of(p["name_a"]).id == index.entity_of(p["name_b"]).id
        tp += truth and pred
        fp += pred and not truth
        fn += truth and not pred
        tn += not truth and not pred
        if truth != pred:
            errors.append({"type": "false_positive" if pred else "false_negative",
                           "name_a": p["name_a"], "name_b": p["name_b"], "note": p["note"]})
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(precision, 3),
            "recall": round(recall, 3), "f1": round(f1, 3), "errors": errors}


# Ablation: each step of the method added in turn. "whole-key threshold" is
# the plain Levenshtein-similarity rule, without the token-level check.
CONFIGS = {
    "phase2_normalisation_only": dict(capacity=False, truncation=False, fuzzy=False),
    "+ capacity_rules":          dict(truncation=False, fuzzy=False),
    "+ truncation":              dict(fuzzy=False),
    "+ fuzzy, whole-key threshold 0.8": dict(token_guard=False, key_threshold=0.8),
    "+ fuzzy, whole-key threshold 0.9": dict(token_guard=False, key_threshold=0.9),
    "+ fuzzy, token check (full method)": dict(),
}
TOKEN_SWEEP = (0.6, 0.7, 0.8, 0.9)


def blocking_benchmark(records, prefixes=(1, 2, 3, 4, 5, 6)):
    """Cost of finding fuzzy-match candidates, three ways, over the distinct
    match keys of each entity type. Every strategy verifies its candidates
    with token_match; "matches" counts verified pairs, "missed" lists pairs
    that comparing all pairs finds but the strategy does not.

      all_pairs          every pair, Levenshtein with early exit at 20% of length
      trie_near_search   Trie.within() per key, radius 20% of length (lossless)
      prefix_blocking_p  only keys sharing the first p characters (Trie.with_prefix)
    """
    keys = defaultdict(set)
    for o in _observations(records):
        keys[o.entity_type].add(o.key)
    keys = {t: sorted(ks) for t, ks in keys.items()}

    def radius(k):
        return max(1, int(len(k) * CANDIDATE_RADIUS))

    def run(pairs_of):
        start, compared, found = time.perf_counter(), 0, set()
        for ks in keys.values():
            for a, b in pairs_of(ks):
                compared += 1
                if levenshtein(a, b, limit=radius(a)) <= radius(a) and token_match(a, b):
                    found.add((a, b))
        return compared, found, time.perf_counter() - start

    def all_pairs(ks):
        return ((a, b) for i, a in enumerate(ks) for b in ks[i + 1:])

    def tries(ks):
        t = Trie()
        for k in ks:
            t.insert(k)
        return t

    out = {}
    compared, truth, secs = run(all_pairs)
    out["all_pairs"] = {"comparisons": compared, "matches": len(truth), "seconds": round(secs, 3)}

    start, found, cells = time.perf_counter(), set(), 0
    for ks in keys.values():
        t = tries(ks)
        for a in ks:
            found |= {(a, b) for b, _, _ in t.within(a, radius(a)) if b > a and token_match(a, b)}
        cells += t.cells
    out["trie_near_search"] = {"edit_distance_cells": cells, "matches": len(found),
                               "seconds": round(time.perf_counter() - start, 3)}

    for p in prefixes:
        def blocked(ks, p=p):
            t = tries(ks)
            return ((a, b) for a in ks for b, _ in t.with_prefix(a[:p]) if b > a)
        compared, found, secs = run(blocked)
        out[f"prefix_blocking_{p}"] = {"comparisons": compared, "matches": len(found),
                                       "seconds": round(secs, 3),
                                       "missed": [f"{a} = {b}" for a, b in sorted(truth - found)]}
    return out


def evaluate(records, pairs):
    report = {"pairs": len(pairs), "positives": sum(p["same_entity"] == "1" for p in pairs),
              "by_band": dict(Counter(p["band"] for p in pairs)), "configs": {}, "token_threshold_sweep": {}}
    for name, kwargs in CONFIGS.items():
        index = build_index(records, **kwargs)
        s = score(pairs, index)
        s["entities"] = len(index)
        report["configs"][name] = s
    # The sweep also lists the fuzzy merges each threshold makes on the whole
    # dataset: the sample alone contains few typo pairs.
    for t in TOKEN_SWEEP:
        index = build_index(records, token_threshold=t)
        s = score(pairs, index)
        row = {k: s[k] for k in ("tp", "fp", "fn", "precision", "recall", "f1")}
        row["fuzzy_merges_full_dataset"] = [f"{a} = {b}" for r, a, b, _ in index.merges if r == "fuzzy"]
        report["token_threshold_sweep"][str(t)] = row
    report["blocking"] = blocking_benchmark(records)
    return report


def main(argv):
    records = read_records(ROOT / "data" / "ownership_relations.csv").records
    if len(argv) > 1 and argv[1] == "sample":
        if PAIRS.exists():
            sys.exit(f"{PAIRS} exists; delete it first to draw a new sample (labels would be lost)")
        rows = sample(records)
        with open(PAIRS, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} pairs to {PAIRS}")
        return
    report = evaluate(records, load_pairs())
    (ROOT / "data" / "er_evaluation.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    for name, s in report["configs"].items():
        print(f"{name:38} P={s['precision']:.3f} R={s['recall']:.3f} F1={s['f1']:.3f} "
              f"(tp={s['tp']} fp={s['fp']} fn={s['fn']}) entities={s['entities']}")
    for t, s in report["token_threshold_sweep"].items():
        print(f"token threshold {t}: P={s['precision']:.3f} R={s['recall']:.3f} F1={s['f1']:.3f} "
              f"fuzzy merges on full dataset={len(s['fuzzy_merges_full_dataset'])}")
    for name, b in report["blocking"].items():
        print(f"{name:20} {b}")


if __name__ == "__main__":
    main(sys.argv)
