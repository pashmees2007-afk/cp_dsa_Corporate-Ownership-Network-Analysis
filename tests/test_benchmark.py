import importlib.util
import json
import math
import unittest
from pathlib import Path

from ownership.benchmark import linear_fit, matrix_bfs, slope, to_matrix
from ownership.graph import OwnershipGraph
from ownership.query import load
from ownership.resolve import Entity
from ownership.structure import bfs_levels
from ownership.synthetic import generate, real_profile

ROOT = Path(__file__).resolve().parent.parent
HAS_REFS = importlib.util.find_spec("networkx") is not None and importlib.util.find_spec("numpy") is not None


class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owners, cls.stakes = real_profile(load().graph)

    def test_shape_matches_the_real_data(self):
        for n in (400, 3000):
            g = generate(n, self.owners, self.stakes, seed=1)
            listed = [x for x in g.nodes if g.nodes[x].listed]
            people = [x for x in g.nodes if g.nodes[x].entity_type == "individual"]
            self.assertEqual(len(g), n)
            self.assertAlmostEqual(g.edge_count / n, 946 / 405, delta=0.15)
            self.assertAlmostEqual(len(listed) / n, 0.114, delta=0.01)
            self.assertAlmostEqual(len(people) / n, 0.319, delta=0.01)
            # only listed companies have owners, and every other node holds something
            self.assertTrue(all(g.nodes[x].listed for x in g.nodes if g.owners(x)))
            self.assertTrue(all(g.holdings(x) for x in g.nodes if not g.nodes[x].listed))
            for c in listed:
                self.assertLessEqual(sum(e.stake for e in g.owners(c)), 0.85 + 1e-9)

    def test_seeded(self):
        a = generate(300, self.owners, self.stakes, seed=5)
        b = generate(300, self.owners, self.stakes, seed=5)
        edges = lambda g: sorted((e.holder, e.held, e.stake) for n in g.nodes for e in g.holdings(n))  # noqa: E731
        self.assertEqual(edges(a), edges(b))


class Fits(unittest.TestCase):
    def test_slope(self):
        xs = [10, 100, 1000]
        self.assertAlmostEqual(slope(xs, [3 * x for x in xs]), 1.0)
        self.assertAlmostEqual(slope(xs, [x * x for x in xs]), 2.0)

    def test_linear_fit(self):
        c, r2 = linear_fit([1, 2, 3], [2, 4, 6])
        self.assertAlmostEqual(c, 2.0)
        self.assertAlmostEqual(r2, 1.0)


class MatrixBfs(unittest.TestCase):
    def test_matches_list_bfs_including_zero_stakes(self):
        g = OwnershipGraph()
        for n in "ABCDX":
            g.add_node(Entity(n, n, "corporate"))
        for h, d, s in [("A", "C", 0.5), ("B", "C", 0.0), ("X", "A", 0.2), ("A", "D", 0.1), ("C", "A", 0.1)]:
            g.add_edge(h, d, s)
        ids, pos, rows = to_matrix(g)
        levels = {ids[i]: lv for i, lv in matrix_bfs(rows, pos["C"]).items()}
        self.assertEqual(levels, bfs_levels(g, "C"))
        self.assertIn("B", levels)                       # the 0.00% holding is still an edge
        self.assertEqual(rows[pos["B"]][pos["C"]], 5e-324)


class SavedResults(unittest.TestCase):
    def test_benchmark_file(self):
        report = json.loads((ROOT / "data" / "benchmark.json").read_text("utf-8"))
        fits = report["fits"]
        for op in ("build", "dfs", "tarjan", "components", "integrated"):
            self.assertLess(abs(fits[op]["loglog_slope"] - 1), 0.25, op)     # linear
        self.assertGreater(fits["bfs_matrix_one"]["loglog_slope"], 1.7)       # quadratic
        self.assertLess(abs(fits["mem_matrix"]["loglog_slope"] - 2), 0.1)
        self.assertLess(abs(fits["mem_list"]["loglog_slope"] - 1), 0.1)
        for name in ("bench_traversals.png", "bench_queries.png", "bench_list_vs_matrix.png"):
            self.assertTrue((ROOT / "docs" / "img" / name).exists())

    def test_verification_file(self):
        report = json.loads((ROOT / "data" / "verification.json").read_text("utf-8"))
        self.assertTrue(report["all_agree"])
        for v in report["summary"].values():
            self.assertEqual(v["cases"], v["agreed"])


@unittest.skipUnless(HAS_REFS, "networkx/numpy not installed")
class Verify(unittest.TestCase):
    def test_small_synthetic_graph_agrees(self):
        from ownership.verify import check_graph
        owners, stakes = real_profile(load().graph)
        g = generate(150, owners, stakes, seed=11)
        companies = sorted(x for x in g.nodes if g.nodes[x].listed)
        for name, (cases, agreed, err) in check_graph(g, companies).items():
            self.assertEqual(cases, agreed, name)
            self.assertTrue(math.isfinite(err) and err < 1e-9, name)


if __name__ == "__main__":
    unittest.main()
