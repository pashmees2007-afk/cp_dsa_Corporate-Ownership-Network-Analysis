import importlib.util
import random
import string
import unittest
from pathlib import Path

from ownership.chains import ownership_chains
from ownership.forest import OwnershipForest
from ownership.graph import OwnershipGraph
from ownership.query import load
from ownership.resolve import Entity
from ownership.similarity import levenshtein
from ownership.structure import circular_groups
from ownership.trie import Trie
from ownership.visual import SubGraph, company_subgraph, group_subgraph, levels, owner_subgraph, render

ROOT = Path(__file__).resolve().parent.parent
HAS_PYVIS = importlib.util.find_spec("pyvis") is not None
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


def graph(edges, people=(), listed=()):
    g = OwnershipGraph()
    for n in sorted({x for e in edges for x in e[:2]}):
        e = Entity(n, n, "individual" if n in people else "corporate")
        e.listed = n in listed
        g.add_node(e)
    for h, d, s in edges:
        g.add_edge(h, d, s)
    g.sort_edges()
    return g


class PrefixWithin(unittest.TestCase):
    def test_examples(self):
        t = Trie()
        for k in ("hindalco industries", "hindustan zinc", "tata steel"):
            t.insert(k)
        self.assertEqual([k for k, _, _ in t.prefix_within("hindalko", 1)], ["hindalco industries"])
        self.assertEqual([k for k, _, d in t.prefix_within("tata", 0)], ["tata steel"])
        self.assertEqual(t.prefix_within("zzzz", 1), [])

    def test_against_brute_force(self):
        rng = random.Random(9)
        alphabet = string.ascii_lowercase[:4] + " "
        words = {"".join(rng.choices(alphabet, k=rng.randint(1, 9))) for _ in range(200)}
        t = Trie()
        for w in words:
            t.insert(w)
        for _ in range(60):
            q = "".join(rng.choices(alphabet, k=rng.randint(1, 6)))
            k = rng.randint(0, 2)
            expected = {}
            for w in words:
                d = min(levenshtein(q, w[:i]) for i in range(len(w) + 1))
                if d <= k:
                    expected[w] = d
            got = {key: d for key, _, d in t.prefix_within(q, k)}
            self.assertEqual(got, expected, (q, k))


class SubGraphs(unittest.TestCase):
    def setUp(self):
        # O owns H; H and X hold each other (a circular group); both hold C; P is a person
        self.g = graph([("O", "H", 0.8), ("H", "C", 0.5), ("X", "C", 0.2), ("H", "X", 0.3), ("X", "H", 0.1),
                        ("P", "X", 0.4)], people={"P"}, listed={"C", "H", "X"})
        self.groups = circular_groups(self.g)

    def test_company_view(self):
        sg = company_subgraph(self.g, "C", self.groups)
        self.assertEqual(sg.focus, "C")
        self.assertEqual(set(sg.nodes), {"C", "H", "X", "O", "P"})
        self.assertTrue(sg.edges[("X", "H")]["circular"])
        self.assertTrue(sg.edges[("H", "X")]["circular"])
        self.assertFalse(sg.edges[("H", "C")]["circular"])
        self.assertEqual({n: v["kind"] for n, v in sg.nodes.items()},
                         {"C": "listed", "H": "listed", "X": "listed", "O": "corporate", "P": "individual"})

    def test_company_view_levels_put_owners_above(self):
        lv = levels(company_subgraph(self.g, "C", self.groups))
        self.assertEqual(lv["C"], max(lv.values()))
        self.assertLess(lv["O"], lv["H"])
        self.assertLess(lv["H"], lv["C"])

    def test_owner_view(self):
        chains = [c for n in ("C", "H", "X") for c in ownership_chains(self.g, n)]
        forest = OwnershipForest.from_chains(chains)
        sg = owner_subgraph(self.g, forest, "O", self.groups)
        self.assertEqual(sg.focus, "O")
        self.assertIn(("O", "H"), sg.edges)
        self.assertIn(("H", "C"), sg.edges)
        lv = levels(sg)
        self.assertEqual(lv["O"], 0)
        self.assertEqual(lv["H"], 1)
        only_h = owner_subgraph(self.g, forest, "O", self.groups, companies=["H"])
        self.assertEqual(set(only_h.edges), {("O", "H")})

    def test_group_view(self):
        sg = group_subgraph(self.g, self.groups[0])
        self.assertEqual(set(sg.edges), {("H", "X"), ("X", "H")})
        self.assertFalse(sg.layered)

    def test_levels_with_only_focus(self):
        sg = SubGraph(focus="A")
        sg.nodes["A"] = {"name": "A", "kind": "listed", "note": ""}
        self.assertEqual(levels(sg), {"A": 0})

    @unittest.skipUnless(HAS_PYVIS, "pyvis not installed")
    def test_render_is_offline_and_complete(self):
        html = render(company_subgraph(self.g, "C", self.groups))
        self.assertIn("vis-network", html)
        self.assertNotIn("bootstrap", html.lower())
        self.assertNotIn('src="http', html)
        self.assertNotIn('href="http', html)
        for name in ("C", "H", "X", "O", "P"):
            self.assertIn(f'"label": "{name}"', html)
        self.assertIn("network.fit()", html)


class ProjectDataset(unittest.TestCase):
    def test_lookup_finds_misspelt_starts(self):
        p = load()
        self.assertEqual(p.index.lookup("hindalko")[0].name, "Hindalco Industries Ltd")
        self.assertEqual(p.index.lookup("cholamandlam")[0].name[:13], "Cholamandalam")

    def test_hindalco_view_marks_the_grasim_loop(self):
        p = load()
        g = p.graph
        h = p.index.lookup("hindalco")[0].id
        sg = company_subgraph(g, h, circular_groups(g))
        circ = {(g.nodes[a].name, g.nodes[b].name) for (a, b), e in sg.edges.items() if e["circular"]}
        self.assertIn(("Grasim Industries Ltd", "Hindalco Industries Ltd"), circ)


@unittest.skipUnless(HAS_STREAMLIT and HAS_PYVIS, "streamlit/pyvis not installed")
class App(unittest.TestCase):
    """Runs app.py headless and checks every view renders without an exception."""

    def test_app_runs(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertIn("### Tata Steel Ltd", [m.value for m in at.markdown])
        at.text_input[0].input("hindalko").run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertIn("### Hindalco Industries Ltd", [m.value for m in at.markdown])
        at.text_input[0].input("tata sons").run()
        self.assertEqual(len(at.exception), 0)
        at.text_input[0].input("qqqqqqqqqqqq").run()
        self.assertTrue(any("No entity matches" in w.value for w in at.warning))


if __name__ == "__main__":
    unittest.main()
