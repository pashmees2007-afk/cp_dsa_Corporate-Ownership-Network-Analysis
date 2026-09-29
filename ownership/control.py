"""Phase 6 - effective control through cross-holdings.

    python -m ownership.control   # -> data/integrated_ownership.csv, data/control_metrics.json

Integrated stake
----------------
The integrated stake of an entity U in a company C is the total weight of
every ownership route from U to C, where a route's weight is the product of
the stakes along it. Routes may go round a loop of cross-holdings any number
of times, but a route ends as soon as it reaches C (C's own holdings do not
feed back into C's owners).

With x_v = integrated stake of v in C:

    x_C = 1
    x_v = sum over v's holdings (v -> w, stake s) of s * x_w        (v != C)

Outside the circular-holding groups the graph has no cycles, so each x_v
follows directly from the x of the companies v holds. The components from
Tarjan's algorithm come out in exactly that order (a component is finished
only after every component it can reach), so one pass over them suffices.

Inside a circular-holding group S the x values depend on each other:
x_S = A_S x_S + b, where A_S is the group's matrix of stakes in each other
and b collects the stakes held outside the group. Hence
x_S = (I + A_S + A_S^2 + ...) b. The series is computed by repeated matrix
multiplication (ownership.matrix.walk_sum): the k-th power adds the routes
that go round the group's loops k times. The series matrix of each group is
computed once and cached, except for the group that contains C, where C's
row is zeroed (routes stop at C) and the matrix depends on C.

Phase 4's ultimate-owner totals add up simple chains only (no repeated
entity), so they miss the routes that go round loops. The difference between
the two is the loop contribution this phase measures.
"""
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import time

from .chains import NATURAL_PERSON, NO_RECORDED_OWNER, iter_chains, ownership_chains, ultimate_owners
from .forest import OwnershipForest
from .matrix import matvec, walk_sum
from .structure import connected_components, is_promoter_edge, tarjan_scc

ROOT = Path(__file__).resolve().parent.parent


class ControlModel:
    """Integrated stakes for one graph. Components and group matrices are
    computed once and reused across target companies."""

    def __init__(self, graph):
        self.graph = graph
        self.components = tarjan_scc(graph)       # successors before predecessors
        self._series = {}                         # (group, target or None) -> (members, series matrix, terms)

    def group_matrix(self, members, target=None):
        """Stake matrix A of a group: A[i][j] = stake of members[i] in members[j].
        With a target in the group, the target's row is zeroed."""
        pos = {n: i for i, n in enumerate(members)}
        a = [[0.0] * len(members) for _ in members]
        for n in members:
            if n == target:
                continue
            for e in self.graph.holdings(n):
                if e.held in pos:
                    a[pos[n]][pos[e.held]] = e.stake
        return a

    def _group_series(self, members, target):
        key = (tuple(members), target if target in members else None)
        if key not in self._series:
            series, terms = walk_sum(self.group_matrix(members, key[1]))
            self._series[key] = (series, terms)
        return self._series[key]

    def integrated(self, target):
        """{entity ID: integrated stake in target} for every entity with a
        non-zero stake, the target itself included (value 1)."""
        g = self.graph
        x = {target: 1.0}
        for comp in self.components:
            if len(comp) == 1:
                v = comp[0]
                if v != target:
                    s = sum(e.stake * x.get(e.held, 0.0) for e in g.holdings(v))
                    if s:
                        x[v] = s
                continue
            members = set(comp)
            b = []
            for v in comp:
                if v == target:
                    b.append(1.0)
                else:
                    b.append(sum(e.stake * x.get(e.held, 0.0) for e in g.holdings(v) if e.held not in members))
            if not any(b):
                continue
            series, _ = self._group_series(comp, target)
            for v, val in zip(comp, matvec(series, b)):
                if val:
                    x[v] = val
        return x

    def self_ownership(self, target, x=None):
        """The target's indirect stake in itself: the weight of routes that
        leave the target and come back to it through a loop."""
        x = self.integrated(target) if x is None else x
        return sum(e.stake * x.get(e.held, 0.0) for e in self.graph.holdings(target))

    def ultimate(self, target, x=None):
        """{entity: integrated stake} for entities with no recorded owner."""
        x = self.integrated(target) if x is None else x
        return {n: s for n, s in x.items() if n != target and not self.graph.owners(n)}


# ---------------------------------------------------------------- metrics

def _clean(x, eps=1e-12):
    """Floating-point noise around zero (e.g. -1e-17) becomes 0."""
    return 0.0 if abs(x) < eps else x


def hhi(stakes):
    """Herfindahl-Hirschman index of stakes in percentage points (0-10,000)."""
    return sum((s * 100) ** 2 for s in stakes)


def company_metrics(model, company, family_of):
    g = model.graph
    x = model.integrated(company)
    owners = model.ultimate(company, x)
    simple = {e: t for e, t, _ in ultimate_owners(iter_chains(g, company, 0.0))}
    ranked = sorted(owners.items(), key=lambda t: (-t[1], t[0]))
    fam = family_of.get(company)
    family_stake = sum(s for n, s in owners.items() if family_of.get(n) == fam)
    ctrl, ctrl_stake = ranked[0] if ranked else (None, 0.0)
    return {
        "company": g.nodes[company].name,
        "family": fam,
        "ultimate_owners": len(owners),
        "traced_pct": sum(owners.values()) * 100,
        "controller": g.nodes[ctrl].name if ctrl else None,
        "controller_type": g.nodes[ctrl].entity_type if ctrl else None,
        "controller_pct": ctrl_stake * 100,
        "controller_simple_chain_pct": simple.get(ctrl, 0.0) * 100,
        "top3_pct": sum(s for _, s in ranked[:3]) * 100,
        "hhi": hhi(owners.values()),
        "family_pct": family_stake * 100,
        "outside_family_pct": (sum(owners.values()) - family_stake) * 100,
        "self_ownership_pct": _clean(model.self_ownership(company, x)) * 100,
        "loop_contribution_pct": _clean(sum(owners.values()) - sum(simple.values())) * 100,
    }, owners, simple


def family_metrics(rows):
    """Control concentration across the listed companies of one family."""
    fam = [r["family_pct"] for r in rows]
    ctrl = Counter(r["controller"] for r in rows)
    return {
        "companies": len(rows),
        "family_pct_mean": statistics.mean(fam),
        "family_pct_median": statistics.median(fam),
        "family_pct_min": min(fam),
        "family_pct_max": max(fam),
        "companies_family_over_50_pct": sum(f > 50 for f in fam),
        "companies_family_25_to_50_pct": sum(25 <= f <= 50 for f in fam),
        "companies_family_under_25_pct": sum(f < 25 for f in fam),
        "controller_pct_mean": statistics.mean(r["controller_pct"] for r in rows),
        "hhi_mean": statistics.mean(r["hhi"] for r in rows),
        "controllers": dict(ctrl.most_common()),
        "loop_contribution_pct_total": sum(r["loop_contribution_pct"] for r in rows),
    }


def analyse(p):
    """Metrics for every listed company and every family, plus the group matrices."""
    g = p.graph
    model = ControlModel(g)
    fam_of, fams = connected_components(g, is_promoter_edge)
    family_id = {}
    k = 0
    for comp in fams:
        if len(comp) > 1:                          # same numbering as the Phase 5 report
            k += 1
            for n in comp:
                family_id[n] = f"F{k}"

    listed = sorted((e.id for e in p.index.entities if e.listed), key=lambda n: g.nodes[n].name.casefold())
    companies, owner_rows = [], []
    for c in listed:
        m, owners, simple = company_metrics(model, c, family_id)
        companies.append(m)
        for n, s in sorted(owners.items(), key=lambda t: -t[1]):
            owner_rows.append({"company": g.nodes[c].name, "owner": g.nodes[n].name,
                               "owner_type": g.nodes[n].entity_type,
                               "same_family": family_id.get(n) == family_id.get(c) and family_id.get(c) is not None,
                               "integrated_pct": round(s * 100, 6),
                               "simple_chains_pct": round(simple.get(n, 0.0) * 100, 6),
                               "loop_pct": round(_clean(s - simple.get(n, 0.0)) * 100, 6)})

    by_family = defaultdict(list)
    for m in companies:
        by_family[m["family"] or "none"].append(m)
    families = {f: family_metrics(rows) for f, rows in sorted(by_family.items())}

    groups = []
    for comp in sorted((c for c in model.components if len(c) > 1), key=lambda c: -len(c)):
        a = model.group_matrix(comp)
        series, terms = walk_sum(a)
        groups.append({"members": [g.nodes[n].name for n in comp],
                       "stake_matrix_pct": [[round(v * 100, 4) for v in row] for row in a],
                       "series_matrix": [[round(v, 6) for v in row] for row in series],
                       "terms_to_converge": terms})
    return {"companies": companies, "families": families, "circular_groups": groups,
            "tree_store": tree_store(g, listed)}, owner_rows


def tree_store(g, companies, repeats=20):
    """Build the owner-rooted forest from every company's Phase 4 chains and
    time repeated chain queries against re-running the traversal."""
    chains = {c: ownership_chains(g, c) for c in companies}
    forest = OwnershipForest.from_chains(ch for cs in chains.values() for ch in cs)
    stored = [ch for cs in chains.values() for ch in cs if ch.end in (NATURAL_PERSON, NO_RECORDED_OWNER)]

    start = time.perf_counter()
    for _ in range(repeats):
        for c in companies:
            ownership_chains(g, c)
    traversal = (time.perf_counter() - start) / repeats

    start = time.perf_counter()
    for _ in range(repeats):
        for c in companies:
            forest.chains_of(c)
    lookup = (time.perf_counter() - start) / repeats

    # owner-side query: what does each owner reach? Without the forest this
    # needs every company's chains (Phase 4 enumerates chains per company).
    owners = list(forest.roots)
    start = time.perf_counter()
    for _ in range(repeats):
        every = [ch for c in companies for ch in ownership_chains(g, c)]
        [ch for ch in every if ch.terminal == owners[0]]
    owner_traversal = (time.perf_counter() - start) / repeats
    start = time.perf_counter()
    for _ in range(repeats):
        for o in owners:
            forest.portfolio(o)
    owner_lookup = (time.perf_counter() - start) / repeats / len(owners)

    return {
        "trees": len(forest.roots),
        "chains_stored": forest.chains_stored,
        "tree_nodes": forest.node_count(),
        "entities_in_stored_chains": sum(len(ch.nodes) for ch in stored),
        "query_all_companies_ms": {"traversal": round(traversal * 1000, 3), "tree_lookup": round(lookup * 1000, 3)},
        "speedup": round(traversal / lookup, 1) if lookup else None,
        "query_one_owner_portfolio_ms": {"traversal": round(owner_traversal * 1000, 3),
                                         "tree_lookup": round(owner_lookup * 1000, 4)},
        "owner_query_speedup": round(owner_traversal / owner_lookup) if owner_lookup else None,
    }


def _round(obj):
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj


def main():
    from .query import load
    report, owner_rows = analyse(load())
    with open(ROOT / "data" / "integrated_ownership.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(owner_rows[0]))
        w.writeheader()
        w.writerows(owner_rows)
    (ROOT / "data" / "control_metrics.json").write_text(json.dumps(_round(report), indent=2) + "\n", "utf-8")
    print(f"{'family':6} {'cos':>3} {'family% mean':>12} {'median':>7} {'>50%':>5} {'25-50%':>6} {'<25%':>5} "
          f"{'HHI mean':>9}  controllers")
    for f, m in report["families"].items():
        print(f"{f:6} {m['companies']:>3} {m['family_pct_mean']:>12.2f} {m['family_pct_median']:>7.2f} "
              f"{m['companies_family_over_50_pct']:>5} {m['companies_family_25_to_50_pct']:>6} "
              f"{m['companies_family_under_25_pct']:>5} {m['hhi_mean']:>9.0f}  {m['controllers']}")
    print(f"\ntree store: {report['tree_store']}")


if __name__ == "__main__":
    main()
