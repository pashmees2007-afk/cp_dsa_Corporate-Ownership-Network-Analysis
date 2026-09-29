import json
import random
import unittest
from pathlib import Path

from ownership.graph import OwnershipGraph
from ownership.ingest import parse_text
from ownership.query import load
from ownership.resolve import Entity
from ownership.structure import (anomaly_report, bfs_levels, circular_groups, connected_components,
                                 find_back_edges, is_promoter_edge, tarjan_scc)

try:
    import networkx as nx
except ImportError:                     # pip install -r requirements-dev.txt
    nx = None

ROOT = Path(__file__).resolve().parent.parent


def graph(edges, nodes=()):
    g = OwnershipGraph()
    for n in sorted({x for e in edges for x in e[:2]} | set(nodes)):
        g.add_node(Entity(n, n, "corporate"))
    for h, d, *s in edges:
        g.add_edge(h, d, s[0] if s else 0.1)
    g.sort_edges()
    return g


def random_graph(rng, n, p):
    names = [f"N{i:02d}" for i in range(n)]
    edges = [(a, b, rng.random()) for a in names for b in names if a != b and rng.random() < p]
    return graph(edges, names)


def to_nx(g, undirected=False):
    G = nx.Graph() if undirected else nx.DiGraph()
    G.add_nodes_from(g.nodes)
    G.add_edges_from((e.holder, e.held) for n in g.nodes for e in g.holdings(n))
    return G


class BackEdges(unittest.TestCase):
    def test_acyclic(self):
        self.assertEqual(find_back_edges(graph([("A", "B"), ("B", "C"), ("A", "C")])), [])

    def test_two_cycle(self):
        [(h, d, cycle)] = find_back_edges(graph([("A", "B"), ("B", "A")]))
        self.assertEqual((h, d, cycle), ("B", "A", ["A", "B", "A"]))

    def test_cycle_is_read_off_the_stack(self):
        found = find_back_edges(graph([("A", "B"), ("B", "C"), ("C", "D"), ("D", "B"), ("A", "E")]))
        self.assertEqual([c for _, _, c in found], [["B", "C", "D", "B"]])

    def test_cross_edge_into_finished_vertex_is_not_a_cycle(self):
        self.assertEqual(find_back_edges(graph([("A", "C"), ("B", "C"), ("C", "D")])), [])

    def test_every_reported_cycle_exists(self):
        rng = random.Random(1)
        for _ in range(100):
            g = random_graph(rng, rng.randint(2, 12), 0.2)
            for holder, held, cycle in find_back_edges(g):
                self.assertEqual((cycle[0], cycle[-1], cycle[-2]), (held, held, holder))
                for a, b in zip(cycle, cycle[1:]):
                    self.assertIn(b, [e.held for e in g.holdings(a)])


class Tarjan(unittest.TestCase):
    def test_textbook_example(self):
        g = graph([("A", "B"), ("B", "C"), ("C", "A"), ("B", "D"), ("D", "E"), ("E", "F"), ("F", "D"),
                   ("G", "F"), ("G", "H"), ("H", "G")])
        self.assertEqual(sorted(map(tuple, tarjan_scc(g))), [("A", "B", "C"), ("D", "E", "F"), ("G", "H")])
        self.assertEqual(circular_groups(g), [["A", "B", "C"], ["D", "E", "F"], ["G", "H"]])

    def test_dag_has_only_singletons(self):
        g = graph([("A", "B"), ("B", "C"), ("A", "C")])
        self.assertEqual(circular_groups(g), [])
        self.assertEqual(len(tarjan_scc(g)), 3)

    def test_long_path_needs_no_recursion(self):
        n = 5000
        edges = [(f"N{i:05d}", f"N{i + 1:05d}") for i in range(n)] + [(f"N{n:05d}", "N00000")]
        g = graph(edges)
        self.assertEqual([len(c) for c in circular_groups(g)], [n + 1])
        self.assertEqual(len(find_back_edges(g)), 1)

    def test_back_edges_lie_inside_circular_groups(self):
        rng = random.Random(2)
        for _ in range(100):
            g = random_graph(rng, rng.randint(2, 12), 0.2)
            in_group = {n for c in circular_groups(g) for n in c}
            for holder, held, cycle in find_back_edges(g):
                self.assertTrue(set(cycle) <= in_group)
            self.assertEqual(bool(find_back_edges(g)), bool(in_group))


class Bfs(unittest.TestCase):
    def test_levels(self):
        # C is owned by A and B; A is owned by X; X is owned by B (so B is at level 1, not 3)
        g = graph([("A", "C"), ("B", "C"), ("X", "A"), ("B", "X"), ("Y", "X")])
        self.assertEqual(bfs_levels(g, "C"), {"C": 0, "A": 1, "B": 1, "X": 2, "Y": 3})

    def test_cycle_terminates(self):
        self.assertEqual(bfs_levels(graph([("A", "B"), ("B", "A")]), "A"), {"A": 0, "B": 1})


class Components(unittest.TestCase):
    def test_undirected_projection(self):
        g = graph([("A", "B"), ("C", "B"), ("D", "E")], nodes=["F"])
        label, comps = connected_components(g)
        self.assertEqual(comps, [["A", "B", "C"], ["D", "E"], ["F"]])
        self.assertEqual(label["C"], label["A"])

    def test_edge_filter(self):
        g = graph([("A", "B", 0.5), ("B", "C", 0.01)])
        _, comps = connected_components(g, lambda e: e.stake > 0.1)
        self.assertEqual(comps, [["A", "B"], ["C"]])

    def test_promoter_filter(self):
        res = parse_text("holder_name,held_name,stake_pct,filing_date,entity_type,holder_role\n"
                         "P Ltd,X Ltd,40,2026-06-30,corporate,Promoter\n"
                         "Fund,X Ltd,2,2026-06-30,corporate,Public (>1%)\n")
        from ownership.resolve import build_index
        idx = build_index(res.records)
        g = OwnershipGraph.from_records(res.records, idx)
        roles = {g.nodes[e.holder].name: is_promoter_edge(e) for e in g.owners(idx.entity_of("X Ltd").id)}
        self.assertEqual(roles, {"P Ltd": True, "Fund": False})


@unittest.skipUnless(nx, "networkx not installed")
class AgainstNetworkX(unittest.TestCase):
    def test_random_graphs(self):
        rng = random.Random(3)
        for _ in range(150):
            g = random_graph(rng, rng.randint(1, 30), rng.choice([0.03, 0.08, 0.2]))
            G = to_nx(g)
            self.assertEqual(sorted(map(tuple, tarjan_scc(g))),
                             sorted(tuple(sorted(c)) for c in nx.strongly_connected_components(G)))
            self.assertEqual(not find_back_edges(g), nx.is_directed_acyclic_graph(G))
            _, comps = connected_components(g)
            self.assertEqual(sorted(map(tuple, comps)),
                             sorted(tuple(sorted(c)) for c in nx.connected_components(to_nx(g, True))))
            for n in list(g.nodes)[:3]:
                self.assertEqual(bfs_levels(g, n), nx.single_source_shortest_path_length(G.reverse(), n))


class ProjectDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = load()
        cls.report = anomaly_report(cls.p)

    def test_circular_groups(self):
        s = self.report["summary"]
        self.assertEqual([x["size"] for x in self.report["circular_holdings"]], [11, 3, 2, 2])
        self.assertEqual(s["companies_in_circular_groups"], 18)
        self.assertIn(["Grasim Industries Ltd", "Hindalco Industries Ltd"],
                      [x["members"] for x in self.report["circular_holdings"]])

    def test_deep_chains_and_families(self):
        s = self.report["summary"]
        self.assertEqual(s["control_depth_distribution"], {1: 37, 2: 9})
        self.assertEqual(s["components_all_edges"], [403, 2])
        self.assertEqual([f["groups"] for f in self.report["families"]],
                         [{"Tata": 24}, {"Murugappa": 10}, {"Aditya Birla": 11}, {"Tata": 1}])

    @unittest.skipUnless(nx, "networkx not installed")
    def test_real_graph_against_networkx(self):
        G = to_nx(self.p.graph)
        self.assertEqual(sorted(map(tuple, tarjan_scc(self.p.graph))),
                         sorted(tuple(sorted(c)) for c in nx.strongly_connected_components(G)))

    def test_report_file_is_current(self):
        saved = json.loads((ROOT / "data" / "anomaly_report.json").read_text("utf-8"))
        self.assertEqual(saved["summary"]["circular_groups"], self.report["summary"]["circular_groups"])
        self.assertEqual(saved["families"], self.report["families"])


if __name__ == "__main__":
    unittest.main()
