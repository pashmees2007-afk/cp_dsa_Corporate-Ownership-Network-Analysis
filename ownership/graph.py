"""Phase 4 - the ownership graph.

A directed weighted graph stored as adjacency lists:

    node    one resolved entity (Phase 3 entity ID)
    edge    holder -> held, weight = stake as a fraction (31.74% -> 0.3174)

Each node keeps two lists: the edges out of it (what it holds) and the edges
into it (who holds it). Chain traversal walks the inbound lists, from a
company up to its owners; later phases use the outbound ones. Both lists
together take O(V + E) space. An adjacency matrix would take O(V^2): this
graph has 405 nodes and 946 edges, so a matrix would be 164,025 cells of
which 0.58% are non-zero.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Edge:
    holder: str                  # entity ID of the owner
    held: str                    # entity ID of the company owned
    stake: float                 # fraction of the held company's shares, 0..1
    records: tuple = ()          # the OwnershipRecords behind this edge


@dataclass
class OwnershipGraph:
    nodes: dict = field(default_factory=dict)      # entity ID -> Entity
    _out: dict = field(default_factory=dict)       # entity ID -> [Edge] it holds
    _in: dict = field(default_factory=dict)        # entity ID -> [Edge] holding it
    _edge_count: int = 0

    def add_node(self, entity):
        if entity.id not in self.nodes:
            self.nodes[entity.id] = entity
            self._out[entity.id] = []
            self._in[entity.id] = []

    def add_edge(self, holder, held, stake, record=None):
        """Add holder -> held. A second filing of the same pair (two rows
        that resolve to the same holder and company) adds its stake to the
        existing edge: they are separate holdings of the same owner."""
        if holder == held:
            raise ValueError(f"self-ownership edge on {holder}")
        for n in (holder, held):
            if n not in self.nodes:
                raise KeyError(f"unknown node {n}")
        records = (record,) if record is not None else ()
        for i, e in enumerate(self._out[holder]):
            if e.held == held:
                merged = Edge(holder, held, e.stake + stake, e.records + records)
                self._out[holder][i] = merged
                self._in[held][[x.holder for x in self._in[held]].index(holder)] = merged
                return merged
        e = Edge(holder, held, stake, records)
        self._out[holder].append(e)
        self._in[held].append(e)
        self._edge_count += 1
        return e

    def owners(self, node):
        """Inbound edges: who holds `node`, largest stake first."""
        return self._in[node]

    def holdings(self, node):
        """Outbound edges: what `node` holds, largest stake first."""
        return self._out[node]

    def __len__(self):
        return len(self.nodes)

    @property
    def edge_count(self):
        return self._edge_count

    def sort_edges(self):
        """Order every adjacency list by stake, largest first (then by ID),
        so traversals visit the biggest owners first."""
        for lists, other in ((self._in, "holder"), (self._out, "held")):
            for n in lists:
                lists[n].sort(key=lambda e: (-e.stake, getattr(e, other)))

    @classmethod
    def from_records(cls, records, index):
        """Build the graph from ingested records and a Phase 3 EntityIndex.
        Every entity in the index becomes a node, even if it has no edges."""
        g = cls()
        for entity in index.entities:
            g.add_node(entity)
        for r in records:
            g.add_edge(index.entity_of(r.holder_name, r.entity_type).id,
                       index.entity_of(r.held_name, "corporate").id,
                       r.stake_pct / 100.0, r)
        g.sort_edges()
        return g
