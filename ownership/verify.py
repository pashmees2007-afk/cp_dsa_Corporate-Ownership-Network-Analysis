"""Phase 8 - correctness cross-verification against reference libraries.

    pip install -r requirements-dev.txt
    python -m ownership.verify           # -> data/verification.json

Every hand-written algorithm is compared with an independent reference
implementation: NetworkX for the graph algorithms, NumPy for the matrix step.
The references are used only here and in the tests, never in the delivered
pipeline. Checks run on the real graph and on synthetic graphs of 100 to 5,000
nodes (the benchmark sizes).

  scc          tarjan_scc                 == nx.strongly_connected_components
  acyclic      find_back_edges() is empty == nx.is_directed_acyclic_graph
  cycles       every reported cycle is a real cycle (its edges exist)
  components   connected_components       == nx.connected_components (undirected)
  bfs          bfs_levels(company)        == nx.single_source_shortest_path_length on the reversed graph
  reachable    reachable_owners(company)  == nx.ancestors
  chains       chains ending at an owner, no threshold == nx.all_simple_paths from every
               source (no inbound edge) to the company
  integrated   ControlModel.integrated    == numpy.linalg.solve((I - A') x = e_C)
"""
import json
import sys
import time
from pathlib import Path

import networkx as nx
import numpy as np

from .chains import NATURAL_PERSON, NO_RECORDED_OWNER, iter_chains, reachable_owners
from .control import ControlModel
from .structure import bfs_levels, connected_components, find_back_edges, is_promoter_edge, tarjan_scc
from .synthetic import generate, real_profile

ROOT = Path(__file__).resolve().parent.parent
SIZES = (100, 500, 1000, 2500, 5000)
SAMPLE = 50                              # companies checked per synthetic graph (all on the real graph)


def to_nx(g, keep=None):
    G = nx.DiGraph()
    G.add_nodes_from(g.nodes)
    G.add_edges_from((e.holder, e.held) for n in g.nodes for e in g.holdings(n) if keep is None or keep(e))
    return G


def _sets(components):
    return sorted(tuple(sorted(c)) for c in components)


def check_graph(g, companies, chains=True):
    """{check: (cases, agreed, max_error)} for one graph."""
    G = to_nx(g)
    R = G.reverse(copy=False)
    out = {}

    out["scc"] = (1, int(_sets(tarjan_scc(g)) == _sets(nx.strongly_connected_components(G))), 0.0)
    back = find_back_edges(g)
    out["acyclic"] = (1, int((not back) == nx.is_directed_acyclic_graph(G)), 0.0)
    good = sum(all(G.has_edge(a, b) for a, b in zip(c, c[1:])) and c[0] == c[-1] for _, _, c in back)
    out["cycles"] = (len(back), good, 0.0)
    _, comps = connected_components(g)
    out["components"] = (1, int(_sets(comps) == _sets(nx.connected_components(G.to_undirected()))), 0.0)

    bfs_ok = reach_ok = chain_ok = 0
    for c in companies:
        bfs_ok += bfs_levels(g, c) == nx.single_source_shortest_path_length(R, c)
        reach_ok += reachable_owners(g, c) == nx.ancestors(G, c)
        if chains:
            ours = {ch.nodes[::-1] for ch in iter_chains(g, c, 0.0) if ch.end in (NATURAL_PERSON, NO_RECORDED_OWNER)}
            ref = set()
            for s in nx.ancestors(G, c):
                if G.in_degree(s) == 0:
                    ref |= {tuple(path) for path in nx.all_simple_paths(G, s, c)}
            chain_ok += ours == ref
    out["bfs"] = (len(companies), bfs_ok, 0.0)
    out["reachable"] = (len(companies), reach_ok, 0.0)
    if chains:
        out["chains"] = (len(companies), chain_ok, 0.0)

    ids = sorted(g.nodes)
    pos = {n: i for i, n in enumerate(ids)}
    model = ControlModel(g)
    worst, agreed = 0.0, 0
    for c in companies:
        a = np.zeros((len(ids), len(ids)))
        for n in ids:
            if n != c:
                for e in g.holdings(n):
                    a[pos[n], pos[e.held]] = e.stake
        e_c = np.zeros(len(ids))
        e_c[pos[c]] = 1.0
        expected = np.linalg.solve(np.eye(len(ids)) - a, e_c)
        x = model.integrated(c)
        err = float(np.max(np.abs(np.array([x.get(n, 0.0) for n in ids]) - expected)))
        worst = max(worst, err)
        agreed += err < 1e-9
    out["integrated"] = (len(companies), agreed, worst)
    return out


def run():
    from .query import load
    p = load()
    g = p.graph
    results = []

    start = time.perf_counter()
    listed = sorted(n for n in g.nodes if g.nodes[n].listed)
    checks = check_graph(g, listed)
    # families: component labelling with the promoter-edge filter (Phase 5)
    _, fams = connected_components(g, is_promoter_edge)
    checks["families"] = (1, int(_sets(fams) == _sets(nx.connected_components(
        to_nx(g, is_promoter_edge).to_undirected()))), 0.0)
    results.append({"graph": "real", "V": len(g), "E": g.edge_count, "checks": checks,
                    "seconds": round(time.perf_counter() - start, 1)})
    print(f"real graph: {len(g)} nodes, {g.edge_count} edges", flush=True)

    owners_dist, stakes_dist = real_profile(g)
    for n in SIZES:
        start = time.perf_counter()
        s = generate(n, owners_dist, stakes_dist, seed=n)
        companies = sorted(x for x in s.nodes if s.nodes[x].listed)
        sample = companies[:: max(1, len(companies) // SAMPLE)][:SAMPLE]
        # chain enumeration against all_simple_paths is exponential in general; kept to <= 1,000 nodes
        checks = check_graph(s, sample, chains=n <= 1000)
        results.append({"graph": f"synthetic {n}", "V": len(s), "E": s.edge_count, "checks": checks,
                        "seconds": round(time.perf_counter() - start, 1)})
        print(f"synthetic {n}: done", flush=True)

    totals = {}
    for r in results:
        for name, (cases, agreed, err) in r["checks"].items():
            t = totals.setdefault(name, [0, 0, 0.0])
            t[0] += cases
            t[1] += agreed
            t[2] = max(t[2], err)
    summary = {k: {"cases": v[0], "agreed": v[1], "max_abs_error": v[2]} for k, v in totals.items()}
    return {"summary": summary, "all_agree": all(v[0] == v[1] for v in totals.values()),
            "graphs": [{**r, "checks": {k: {"cases": c, "agreed": a, "max_abs_error": e}
                                        for k, (c, a, e) in r["checks"].items()}} for r in results]}


def main():
    report = run()
    (ROOT / "data" / "verification.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    for name, v in report["summary"].items():
        print(f"{name:12} {v['agreed']:>5} / {v['cases']:<5} max error {v['max_abs_error']:.1e}")
    print("ALL AGREE" if report["all_agree"] else "DISAGREEMENT FOUND")
    sys.exit(0 if report["all_agree"] else 1)


if __name__ == "__main__":
    main()
