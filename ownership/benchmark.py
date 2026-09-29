"""Phase 8 - runtime and memory benchmarks.

    python -m ownership.benchmark        # -> data/benchmark.json, docs/img/bench_*.png

For each graph size (synthetic graphs shaped like the real data, see
ownership.synthetic) it measures:

  build        building the adjacency lists from an edge list        O(V + E)
  dfs          full DFS with white/grey/black states (back edges)     O(V + E)
  tarjan       Tarjan's strongly connected components                 O(V + E)
  components   component labelling of the undirected projection      O(V + E)
  bfs          one BFS over owner edges, mean over up to 20 companies O(V + E) each
  chains       every company's chains at the 0.01% threshold          O(output)
  integrated   integrated stakes for one company (Phase 6)            O(V + E) + group matrices

and compares the adjacency list with an adjacency matrix: the memory each
takes, and the time of one BFS on each (O(V + E) against O(V^2)).

Times are the minimum of several runs (the least-disturbed run) with
time.perf_counter; memory is measured with tracemalloc. Growth is summarised
by the slope of log(time) against log(size): 1 means linear, 2 quadratic.
"""
import json
import math
import time
import tracemalloc
from array import array
from collections import deque
from pathlib import Path

from .chains import iter_chains
from .control import ControlModel
from .graph import OwnershipGraph
from .structure import bfs_levels, connected_components, find_back_edges, tarjan_scc
from .synthetic import generate, real_profile

ROOT = Path(__file__).resolve().parent.parent
SIZES = (100, 250, 500, 1000, 2500, 5000, 10000)
MATRIX_MAX = 5000          # a 10,000-node matrix of doubles is 800 MB: estimated, not built


def best_time(fn, repeats):
    best = math.inf
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def edge_list(g):
    return [(e.holder, e.held, e.stake) for n in g.nodes for e in g.holdings(n)]


def rebuild(g, edges):
    h = OwnershipGraph()
    for entity in g.nodes.values():
        h.add_node(entity)
    for a, b, s in edges:
        h.add_edge(a, b, s)
    return h


# ---------------------------------------------------------------- matrix representation

def to_matrix(g):
    """Dense V x V adjacency matrix of stakes: one array of doubles per row.
    A filed holding that rounds to 0.00% is still an edge, but 0.0 in a stake
    matrix means "no edge", so it is stored as the smallest positive double
    (5e-324): present, and negligible in any product."""
    ids = sorted(g.nodes)
    pos = {n: i for i, n in enumerate(ids)}
    rows = [array("d", bytes(8 * len(ids))) for _ in ids]
    for n in ids:
        for e in g.holdings(n):
            rows[pos[n]][pos[e.held]] = e.stake or 5e-324
    return ids, pos, rows


def matrix_bfs(rows, source):
    """BFS over owner edges on the matrix: the owners of v are the non-zero
    entries of column v, so every visited vertex costs a scan of V rows."""
    level = {source: 0}
    queue = deque([source])
    k = len(rows)
    while queue:
        v = queue.popleft()
        for h in range(k):
            if rows[h][v] and h not in level:
                level[h] = level[v] + 1
                queue.append(h)
    return level


def measure_memory(build):
    tracemalloc.start()
    obj = build()
    size, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return size, obj


# ---------------------------------------------------------------- run

def run(sizes=SIZES, seed=0):
    from .query import load
    owners_dist, stakes_dist = real_profile(load().graph)
    results = []
    for n in sizes:
        g = generate(n, owners_dist, stakes_dist, seed=seed + n)
        V, E = len(g), g.edge_count
        reps = 5 if n <= 1000 else 3
        edges = edge_list(g)
        companies = sorted(x for x in g.nodes if g.nodes[x].listed)
        sample = companies[:: max(1, len(companies) // 20)][:20]

        r = {"n": n, "V": V, "E": E, "companies": len(companies)}
        r["build"] = best_time(lambda: rebuild(g, edges), reps)
        r["dfs"] = best_time(lambda: find_back_edges(g), reps)
        r["tarjan"] = best_time(lambda: tarjan_scc(g), reps)
        r["components"] = best_time(lambda: connected_components(g), reps)
        r["bfs"] = best_time(lambda: [bfs_levels(g, c) for c in sample], reps) / len(sample)

        counted = {}

        def all_chains():
            total = length = 0
            for c in companies:
                for ch in iter_chains(g, c):
                    total += 1
                    length += len(ch.nodes)
            counted["chains"], counted["chain_entities"] = total, length

        r["chains_time"] = best_time(all_chains, reps)
        r.update(counted)

        model = ControlModel(g)
        r["scc_sizes"] = sorted((len(c) for c in model.components if len(c) > 1), reverse=True)
        r["integrated"] = best_time(lambda: [model.integrated(c) for c in sample], reps) / len(sample)

        # adjacency list vs matrix
        r["mem_list_bytes"], _ = measure_memory(lambda: rebuild(g, edges))
        lean = {x: [(e.holder, e.stake) for e in g.owners(x)] for x in g.nodes}
        r["mem_list_lean_bytes"], _ = measure_memory(
            lambda: {x: [(a, s) for a, s in lean[x]] for x in lean})
        source = max(sample, key=lambda c: len(bfs_levels(g, c)))
        r["bfs_list_one"] = best_time(lambda: bfs_levels(g, source), reps)
        if n <= MATRIX_MAX:
            r["mem_matrix_bytes"], (ids, pos, rows) = measure_memory(lambda: to_matrix(g))
            r["bfs_matrix_one"] = best_time(lambda: matrix_bfs(rows, pos[source]), 1 if n > 1000 else reps)
            assert set(ids[i] for i in matrix_bfs(rows, pos[source])) == set(bfs_levels(g, source))
            del rows
        else:
            r["mem_matrix_bytes_estimated"] = 8 * V * V
        results.append(r)
        print(f"n={n:>6} V+E={V + E:>6}  dfs {r['dfs'] * 1e3:8.2f} ms  tarjan {r['tarjan'] * 1e3:8.2f} ms  "
              f"chains {r['chains_time']:6.3f} s ({r['chains']} chains)  "
              f"mem list {r['mem_list_bytes'] / 1e6:6.2f} MB  matrix "
              f"{r.get('mem_matrix_bytes', r.get('mem_matrix_bytes_estimated')) / 1e6:8.1f} MB", flush=True)
    return results


def slope(xs, ys):
    """Least-squares slope of log(y) against log(x)."""
    lx, ly = [math.log(x) for x in xs], [math.log(y) for y in ys]
    mx, my = sum(lx) / len(lx), sum(ly) / len(ly)
    return sum((a - mx) * (b - my) for a, b in zip(lx, ly)) / sum((a - mx) ** 2 for a in lx)


def linear_fit(xs, ys):
    """y = c * x through the origin: (c, R^2)."""
    c = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)
    my = sum(ys) / len(ys)
    ss_res = sum((y - c * x) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    return c, 1 - ss_res / ss_tot if ss_tot else 1.0


def summarise(results):
    size = [r["V"] + r["E"] for r in results]
    out = {}
    for op in ("build", "dfs", "tarjan", "components", "bfs", "integrated"):
        ys = [r[op] for r in results]
        c, r2 = linear_fit(size, ys)
        out[op] = {"x": "V+E", "loglog_slope": round(slope(size, ys), 3), "ns_per_element": round(c * 1e9, 1),
                   "r2_linear": round(r2, 4)}
    ys = [r["chains_time"] for r in results]
    xs = [r["chain_entities"] for r in results]
    c, r2 = linear_fit(xs, ys)
    out["chains"] = {"x": "entities in output chains", "loglog_slope": round(slope(xs, ys), 3),
                     "ns_per_element": round(c * 1e9, 1), "r2_linear": round(r2, 4)}
    m = [r for r in results if "bfs_matrix_one" in r]
    out["bfs_matrix_one"] = {"x": "V", "loglog_slope": round(slope([r["V"] for r in m],
                                                                    [r["bfs_matrix_one"] for r in m]), 3)}
    out["bfs_list_one"] = {"x": "V+E", "loglog_slope": round(slope(size, [r["bfs_list_one"] for r in results]), 3)}
    out["mem_matrix"] = {"x": "V", "loglog_slope": round(slope([r["V"] for r in m],
                                                                [r["mem_matrix_bytes"] for r in m]), 3)}
    out["mem_list"] = {"x": "V+E", "loglog_slope": round(slope(size, [r["mem_list_bytes"] for r in results]), 3)}
    return out


def main():
    results = run()
    report = {"sizes": results, "fits": summarise(results),
              "machine_note": "single run on the development container; absolute times vary by machine"}
    (ROOT / "data" / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    from .plots import plot_benchmarks
    plot_benchmarks(report, ROOT / "docs" / "img")
    print(json.dumps(report["fits"], indent=2))


if __name__ == "__main__":
    main()
