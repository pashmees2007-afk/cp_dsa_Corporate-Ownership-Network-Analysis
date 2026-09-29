import json
import random
import unittest
from pathlib import Path

from ownership.chains import NATURAL_PERSON, NO_RECORDED_OWNER, iter_chains, ownership_chains, ultimate_owners
from ownership.control import ControlModel, analyse, hhi
from ownership.forest import OwnershipForest
from ownership.graph import OwnershipGraph
from ownership.matrix import identity, matmul, walk_sum
from ownership.query import load
from ownership.resolve import Entity

try:
    import numpy as np
except ImportError:                     # pip install -r requirements-dev.txt
    np = None

ROOT = Path(__file__).resolve().parent.parent


def graph(edges, people=()):
    g = OwnershipGraph()
    for n in sorted({x for e in edges for x in e[:2]}):
        g.add_node(Entity(n, n, "individual" if n in people else "corporate"))
    for h, d, s in edges:
        g.add_edge(h, d, s)
    g.sort_edges()
    return g


def random_graph(rng, n, p, acyclic=False):
    """Random stakes, scaled so no company is more than 90% held."""
    names = [f"N{i:02d}" for i in range(n)]
    edges = {}
    for j, held in enumerate(names):
        holders = [h for i, h in enumerate(names) if h != held and (i < j or not acyclic) and rng.random() < p]
        raw = [rng.random() for _ in holders]
        total = sum(raw) / 0.9 if sum(raw) > 0.9 else 1.0
        for h, r in zip(holders, raw):
            edges[(h, held)] = r / total
    return graph([(h, d, s) for (h, d), s in edges.items()])


class Matrix(unittest.TestCase):
    def test_matmul(self):
        self.assertEqual(matmul([[1, 2], [3, 4]], [[5, 6], [7, 8]]), [[19, 22], [43, 50]])
        self.assertEqual(matmul(identity(3), [[1, 2, 3]] * 3), [[1, 2, 3]] * 3)

    def test_walk_sum_of_two_cycle(self):
        # A holds 40% of B, B holds 50% of A: walks A->A have weight 0.2^k
        series, terms = walk_sum([[0.0, 0.4], [0.5, 0.0]])
        self.assertAlmostEqual(series[0][0], 1 / (1 - 0.2))
        self.assertAlmostEqual(series[0][1], 0.4 / (1 - 0.2))
        self.assertGreater(terms, 10)

    def test_nilpotent_matrix_stops_early(self):
        series, terms = walk_sum([[0.0, 0.5], [0.0, 0.0]])
        self.assertEqual(series, [[1.0, 0.5], [0.0, 1.0]])
        self.assertEqual(terms, 2)

    def test_full_ownership_loop_does_not_converge(self):
        with self.assertRaises(ArithmeticError):
            walk_sum([[0.0, 1.0], [1.0, 0.0]], max_iter=200)

    @unittest.skipUnless(np, "numpy not installed")
    def test_walk_sum_equals_inverse(self):
        rng = random.Random(5)
        for _ in range(50):
            k = rng.randint(1, 12)
            a = [[rng.random() * 0.9 / k if i != j else 0.0 for j in range(k)] for i in range(k)]
            series, _ = walk_sum(a)
            np.testing.assert_allclose(series, np.linalg.inv(np.eye(k) - np.array(a)), rtol=1e-9, atol=1e-12)


class Integrated(unittest.TestCase):
    def test_hand_computed_loop(self):
        # U holds 50% of A; A and B hold each other; both hold C
        g = graph([("U", "A", 0.5), ("A", "C", 0.6), ("A", "B", 0.3), ("B", "A", 0.2), ("B", "C", 0.1)])
        x = ControlModel(g).integrated("C")
        x_a = 0.63 / 0.94                          # x_A = 0.6 + 0.3 x_B, x_B = 0.1 + 0.2 x_A
        self.assertAlmostEqual(x["A"], x_a)
        self.assertAlmostEqual(x["B"], 0.1 + 0.2 * x_a)
        self.assertAlmostEqual(x["U"], 0.5 * x_a)
        # simple chains miss the routes that go round the A-B loop
        simple = dict((e, t) for e, t, _ in ultimate_owners(iter_chains(g, "C", 0.0)))
        self.assertAlmostEqual(simple["U"], 0.5 * (0.6 + 0.3 * 0.1))
        self.assertGreater(x["U"], simple["U"])

    def test_routes_stop_at_the_target(self):
        # C holds 30% of A and A holds 40% of C: nothing loops back into A's stake
        g = graph([("A", "C", 0.4), ("C", "A", 0.3), ("U", "A", 0.5)])
        m = ControlModel(g)
        x = m.integrated("C")
        self.assertAlmostEqual(x["A"], 0.4)
        self.assertAlmostEqual(x["U"], 0.2)
        self.assertAlmostEqual(m.self_ownership("C"), 0.12)

    def test_unrelated_entities_are_absent(self):
        g = graph([("A", "C", 0.4), ("B", "D", 0.3)])
        self.assertEqual(ControlModel(g).integrated("C"), {"C": 1.0, "A": 0.4})

    def test_acyclic_graphs_match_simple_chains(self):
        rng = random.Random(6)
        for _ in range(100):
            g = random_graph(rng, rng.randint(2, 10), 0.35, acyclic=True)
            m = ControlModel(g)
            for c in g.nodes:
                ult = m.ultimate(c)
                simple = {e: t for e, t, _ in ultimate_owners(iter_chains(g, c, 0.0))}
                self.assertEqual(set(ult), set(simple))
                for e in ult:
                    self.assertAlmostEqual(ult[e], simple[e])

    def test_loops_only_add(self):
        rng = random.Random(7)
        for _ in range(100):
            g = random_graph(rng, rng.randint(2, 8), 0.35)
            m = ControlModel(g)
            for c in g.nodes:
                ult = m.ultimate(c)
                for e, t, _ in ultimate_owners(iter_chains(g, c, 0.0)):
                    self.assertGreaterEqual(ult[e], t - 1e-12)
                self.assertLessEqual(sum(ult.values()), 1.0 + 1e-9)

    @unittest.skipUnless(np, "numpy not installed")
    def test_against_linear_solve(self):
        rng = random.Random(8)
        for _ in range(100):
            g = random_graph(rng, rng.randint(2, 15), rng.choice([0.1, 0.3]))
            ids = sorted(g.nodes)
            pos = {n: i for i, n in enumerate(ids)}
            m = ControlModel(g)
            for target in ids[:4]:
                a = np.zeros((len(ids), len(ids)))
                for n in ids:
                    if n != target:
                        for e in g.holdings(n):
                            a[pos[n], pos[e.held]] = e.stake
                e_c = np.zeros(len(ids))
                e_c[pos[target]] = 1.0
                expected = np.linalg.solve(np.eye(len(ids)) - a, e_c)
                x = m.integrated(target)
                np.testing.assert_allclose([x.get(n, 0.0) for n in ids], expected, atol=1e-10)

    def test_hhi(self):
        self.assertAlmostEqual(hhi([0.5, 0.5]), 5000)
        self.assertEqual(hhi([]), 0)


class Forest(unittest.TestCase):
    def test_tree_shares_prefixes(self):
        g = graph([("O", "H", 0.8), ("H", "X", 0.5), ("H", "Y", 0.4), ("P", "X", 0.2)], people={"P"})
        chains = [c for n in ("H", "X", "Y") for c in ownership_chains(g, n)]
        f = OwnershipForest.from_chains(chains)
        self.assertEqual(set(f.roots), {"O", "P"})
        self.assertEqual(f.chains_stored, 4)
        self.assertEqual(f.node_count(), 6)         # O, H, X, Y under O; P, X under P
        self.assertEqual({c.nodes for c in f.chains_of("X")}, {("X", "H", "O"), ("X", "P")})
        self.assertAlmostEqual(f.portfolio("O")["X"], 0.4)
        self.assertEqual(f.roots["O"].children["H"].children["X"].path(), ["X", "H", "O"])

    def test_circular_and_below_threshold_chains_are_not_stored(self):
        g = graph([("A", "C", 0.5), ("C", "A", 0.2), ("B", "C", 0.001), ("Z", "B", 0.01)])
        chains = ownership_chains(g, "C")
        f = OwnershipForest.from_chains(chains)
        self.assertEqual(f.chains_stored, 0)
        self.assertEqual(f.chains_of("C"), [])


class ProjectDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = load()
        cls.report, cls.rows = analyse(cls.p)
        cls.by_name = {c["company"]: c for c in cls.report["companies"]}

    def test_forest_reproduces_phase4_chains(self):
        g = self.p.graph
        listed = [e.id for e in self.p.index.entities if e.listed]
        chains = {c: ownership_chains(g, c) for c in listed}
        f = OwnershipForest.from_chains(ch for cs in chains.values() for ch in cs)
        for c in listed:
            expected = [ch for ch in chains[c] if ch.end in (NATURAL_PERSON, NO_RECORDED_OWNER)]
            got = f.chains_of(c)
            self.assertEqual([(x.nodes, x.end) for x in got], [(x.nodes, x.end) for x in expected])
            for x, y in zip(got, expected):
                self.assertAlmostEqual(x.effective, y.effective)

    def test_loops_add_little(self):
        loops = [c["loop_contribution_pct"] for c in self.report["companies"]]
        self.assertTrue(all(0 <= x < 0.1 for x in loops))
        self.assertAlmostEqual(self.by_name["UltraTech Cement Ltd"]["loop_contribution_pct"], 0.0552, places=3)

    def test_grasim_hindalco_self_ownership(self):
        for name in ("Grasim Industries Ltd", "Hindalco Industries Ltd"):
            self.assertAlmostEqual(self.by_name[name]["self_ownership_pct"], 3.92 * 4.29 / 100, places=6)

    def test_controllers_and_families(self):
        self.assertEqual(self.by_name["Tata Steel Ltd"]["controller"], "Tata Sons Private Limited")
        self.assertEqual(self.report["families"]["F2"]["controllers"], {"AMBADI INVESTMENTS LIMITED": 10})
        for c in self.report["companies"]:
            self.assertLessEqual(c["traced_pct"], 100)
            self.assertLessEqual(c["family_pct"], c["traced_pct"] + 1e-9)

    def test_saved_report_is_current(self):
        saved = json.loads((ROOT / "data" / "control_metrics.json").read_text("utf-8"))
        self.assertEqual([c["controller"] for c in saved["companies"]],
                         [c["controller"] for c in self.report["companies"]])
        for s, c in zip(saved["companies"], self.report["companies"]):
            self.assertAlmostEqual(s["family_pct"], c["family_pct"], places=3)


if __name__ == "__main__":
    unittest.main()
