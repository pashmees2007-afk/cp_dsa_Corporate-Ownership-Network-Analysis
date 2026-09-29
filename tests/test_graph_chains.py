import csv
import io
import json
import random
import unittest
from pathlib import Path

from ownership.chains import (CIRCULAR, BELOW_THRESHOLD, NATURAL_PERSON, NO_RECORDED_OWNER,
                              iter_chains, ownership_chains, reachable_owners, ultimate_owners)
from ownership.graph import OwnershipGraph
from ownership.query import describe, load
from ownership.resolve import Entity

ROOT = Path(__file__).resolve().parent.parent


def graph(people=(), edges=()):
    """edges: (holder, held, stake fraction). Names in `people` are individuals."""
    g = OwnershipGraph()
    names = {n for e in edges for n in e[:2]} | set(people)
    for n in sorted(names):
        g.add_node(Entity(n, n, "individual" if n in people else "corporate"))
    for h, d, s in edges:
        g.add_edge(h, d, s)
    g.sort_edges()
    return g


def shape(chains):
    return {(c.nodes, c.end) for c in chains}


class Graph(unittest.TestCase):
    def test_adjacency_lists(self):
        g = graph(edges=[("A", "C", 0.3), ("B", "C", 0.5), ("A", "D", 0.1)])
        self.assertEqual((len(g), g.edge_count), (4, 3))
        self.assertEqual([e.holder for e in g.owners("C")], ["B", "A"])      # largest stake first
        self.assertEqual([e.held for e in g.holdings("A")], ["C", "D"])
        self.assertEqual(g.owners("A"), [])

    def test_parallel_filings_add_up(self):
        g = graph(edges=[("A", "C", 0.3), ("A", "C", 0.2)])
        self.assertEqual(g.edge_count, 1)
        self.assertAlmostEqual(g.owners("C")[0].stake, 0.5)
        self.assertIs(g.owners("C")[0], g.holdings("A")[0])

    def test_self_loop_and_unknown_node(self):
        g = graph(edges=[("A", "B", 0.1)])
        with self.assertRaises(ValueError):
            g.add_edge("A", "A", 0.1)
        with self.assertRaises(KeyError):
            g.add_edge("A", "Z", 0.1)


class Chains(unittest.TestCase):
    def test_linear_chain_to_person(self):
        g = graph(people={"P"}, edges=[("A", "C", 0.5), ("P", "A", 0.4)])
        [c] = ownership_chains(g, "C")
        self.assertEqual((c.nodes, c.stakes, c.end, c.layers), (("C", "A", "P"), (0.5, 0.4), NATURAL_PERSON, 2))
        self.assertAlmostEqual(c.effective, 0.2)

    def test_stops_at_entity_without_owner(self):
        [c] = ownership_chains(graph(edges=[("H", "C", 0.6)]), "C")
        self.assertEqual((c.nodes, c.end), (("C", "H"), NO_RECORDED_OWNER))

    def test_stops_at_person_even_if_person_has_inbound_edges(self):
        g = graph(people={"P"}, edges=[("P", "C", 0.5), ("X", "P", 0.5)])
        self.assertEqual(shape(ownership_chains(g, "C")), {(("C", "P"), NATURAL_PERSON)})

    def test_multi_parent_ranked_by_effective_stake(self):
        g = graph(people={"P", "Q"}, edges=[("A", "C", 0.6), ("B", "C", 0.3), ("P", "A", 0.2),
                                            ("Q", "A", 0.8), ("P", "B", 0.9)])
        chains = ownership_chains(g, "C")
        self.assertEqual([c.nodes for c in chains], [("C", "A", "Q"), ("C", "B", "P"), ("C", "A", "P")])
        self.assertEqual([round(c.effective, 3) for c in chains], [0.48, 0.27, 0.12])
        [(p, total, routes)] = [o for o in ultimate_owners(chains) if o[0] == "P"]
        self.assertAlmostEqual(total, 0.39)
        self.assertEqual(routes, 2)

    def test_circular_holding_terminates_and_shows_the_loop(self):
        g = graph(edges=[("A", "C", 0.5), ("B", "A", 0.4), ("A", "B", 0.3), ("H", "B", 0.6)])
        self.assertEqual(shape(ownership_chains(g, "C")),
                         {(("C", "A", "B", "A"), CIRCULAR), (("C", "A", "B", "H"), NO_RECORDED_OWNER)})

    def test_mutual_holding_with_queried_company(self):
        g = graph(edges=[("A", "C", 0.5), ("C", "A", 0.2)])
        self.assertEqual(shape(ownership_chains(g, "C")), {(("C", "A", "C"), CIRCULAR)})

    def test_below_threshold(self):
        g = graph(edges=[("A", "C", 0.01), ("X", "A", 0.005), ("H", "C", 0.5)])
        self.assertEqual(shape(ownership_chains(g, "C", min_effective=0.0001)),
                         {(("C", "H"), NO_RECORDED_OWNER), (("C", "A"), BELOW_THRESHOLD)})
        self.assertEqual(shape(ownership_chains(g, "C", min_effective=0.02)), {(("C", "H"), NO_RECORDED_OWNER)})
        self.assertIn((("C", "A", "X"), NO_RECORDED_OWNER), shape(ownership_chains(g, "C", min_effective=0)))

    def test_zero_threshold_keeps_zero_stakes(self):
        g = graph(edges=[("A", "C", 0.0)])
        self.assertEqual(len(ownership_chains(g, "C", 0.0)), 1)
        self.assertEqual(ownership_chains(g, "C"), [])

    def test_no_owners(self):
        self.assertEqual(ownership_chains(graph(edges=[("A", "C", 0.5)]), "A"), [])

    def test_reachable_owners(self):
        g = graph(edges=[("A", "C", 0.5), ("B", "A", 0.4), ("A", "B", 0.3), ("C", "D", 0.1)])
        self.assertEqual(reachable_owners(g, "C"), {"A", "B"})
        self.assertEqual(reachable_owners(g, "B"), {"A"})
        self.assertEqual(reachable_owners(g, "D"), {"A", "B", "C"})


def reference_chains(g, company, min_effective):
    """Independent recursive enumeration, to check the explicit-stack version."""
    out = []

    def go(nodes, stakes, eff):
        produced = False
        for e in g.owners(nodes[-1]):
            x = eff * e.stake
            if x < min_effective:
                continue
            produced = True
            o = e.holder
            if o in nodes:
                out.append((nodes + (o,), CIRCULAR))
            elif g.nodes[o].entity_type == "individual":
                out.append((nodes + (o,), NATURAL_PERSON))
            elif not g.owners(o):
                out.append((nodes + (o,), NO_RECORDED_OWNER))
            else:
                go(nodes + (o,), stakes + (e.stake,), x)
        if not produced and len(nodes) > 1:
            out.append((nodes, BELOW_THRESHOLD))

    if g.owners(company):
        go((company,), (), 1.0)
    return out


class AgainstReference(unittest.TestCase):
    def test_random_graphs(self):
        rng = random.Random(4)
        for trial in range(200):
            n = rng.randint(2, 9)
            names = [f"N{i}" for i in range(n)]
            people = {x for x in names if rng.random() < 0.25}
            edges = {(a, b): rng.choice([0.0, 0.001, 0.05, 0.3, 0.7])
                     for a in names for b in names if a != b and rng.random() < 0.3}
            g = graph(people, [(a, b, s) for (a, b), s in edges.items()])
            for company in names:
                if company not in g.nodes:
                    continue
                for m in (0.0, 0.0001, 0.01):
                    got = [(c.nodes, c.end) for c in iter_chains(g, company, m)]
                    ref = reference_chains(g, company, m)
                    self.assertEqual(sorted(got), sorted(ref), (trial, company, m))
                    self.assertEqual(len(got), len(set(got)))          # no chain twice
                    for c in iter_chains(g, company, m):
                        body = c.nodes[:-1] if c.end == CIRCULAR else c.nodes
                        self.assertEqual(len(body), len(set(body)))     # simple path
                        prod = 1.0
                        for s in c.stakes:
                            prod *= s
                        self.assertAlmostEqual(prod, c.effective)


class ProjectDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = load()

    def test_graph_size(self):
        g = self.p.graph
        self.assertEqual((len(g), g.edge_count), (405, 946))
        self.assertEqual(sum(1 for n in g.nodes if g.owners(n)), 46)

    def test_tata_steel(self):
        ts = self.p.index.lookup("tata steel")[0]
        top = ownership_chains(self.p.graph, ts.id)[0]
        self.assertEqual(self.p.graph.nodes[top.terminal].name, "Tata Sons Private Limited")
        self.assertAlmostEqual(top.effective, 0.3176)

    def test_hindalco_grasim_loop(self):
        h = self.p.index.lookup("hindalco")[0]
        circular = [c for c in ownership_chains(self.p.graph, h.id) if c.end == CIRCULAR]
        names = [self.p.graph.nodes[n].name for n in circular[0].nodes]
        self.assertEqual(names, ["Hindalco Industries Ltd", "Grasim Industries Ltd", "Hindalco Industries Ltd"])

    def test_chain_totals(self):
        listed = [e.id for e in self.p.index.entities if e.listed]
        self.assertEqual(sum(1 for c in listed for _ in iter_chains(self.p.graph, c)), 1570)
        self.assertEqual(sum(1 for c in listed for _ in iter_chains(self.p.graph, c, 0.0)), 313822)

    def test_describe(self):
        out = io.StringIO()
        chains = describe(self.p, "TATA STEL", out=out)
        text = out.getvalue()
        self.assertTrue(text.startswith("Tata Steel Ltd"))
        self.assertIn("Tata Sons Private Limited", text)
        self.assertEqual(len(chains), 15)

    def test_describe_entity_without_owners(self):
        out = io.StringIO()
        self.assertEqual(describe(self.p, "tata sons", out=out), [])
        self.assertIn("holds shares in 16 listed companies", out.getvalue())

    def test_describe_no_match(self):
        out = io.StringIO()
        describe(self.p, "qqqqqqqqqqqq", out=out)
        self.assertIn("No entity matches", out.getvalue())

    def test_report_files_agree(self):
        report = json.loads((ROOT / "data" / "chains_report.json").read_text("utf-8"))
        with open(ROOT / "data" / "ownership_chains.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), report["chains"])
        self.assertEqual(sum(c["chains"] for c in report["companies"]), len(rows))


if __name__ == "__main__":
    unittest.main()
