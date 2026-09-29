"""Phase 8 - synthetic ownership graphs for scaling experiments.

The real graph has 405 nodes. To measure how the algorithms scale to 5,000
nodes and beyond, this generator builds graphs of any size with the real
graph's shape (measured in Phase 8, see docs/report.md):

    11.4% of nodes are listed companies (the only nodes with owners)
    31.9% of nodes are natural persons
    owners per company drawn from the real distribution (mean 20.6)
    10.8% of edges come from another listed company (this creates chains and loops)
    other holders: every one holds at least one company; extra holdings go
                   preferentially to holders that already hold more (a few
                   funds hold many companies, most holders hold one)
    stakes drawn from the real stakes, scaled so that a company's recorded
    owners hold 50-85% of it

So E is about 2.35 V, as in the real data, and the circular structures grow
with the graph. The generator is seeded, so every size is reproducible.
"""
import random

from .graph import OwnershipGraph
from .resolve import Entity

LISTED_SHARE = 0.114
PERSON_SHARE = 0.319
COMPANY_HOLDER_SHARE = 0.108


def real_profile(graph):
    """Owners-per-company and stake samples from a real OwnershipGraph."""
    listed = [n for n in graph.nodes if graph.nodes[n].listed]
    owners = [len(graph.owners(n)) for n in listed]
    stakes = [e.stake for n in graph.nodes for e in graph.holdings(n)]
    return owners, stakes


def generate(n, owners_dist, stakes_dist, seed=0):
    """An OwnershipGraph with n nodes shaped like the real data."""
    rng = random.Random(seed)
    m = max(2, round(n * LISTED_SHARE))
    persons = round(n * PERSON_SHARE)
    ids = [f"S{i:06d}" for i in range(n)]
    companies, holders = ids[:m], ids[m:]
    g = OwnershipGraph()
    for i, nid in enumerate(ids):
        e = Entity(nid, nid, "individual" if m <= i < m + persons else "corporate")
        e.listed = i < m
        g.add_node(e)

    # owner slots per company, from the real distribution, scaled so the
    # total number of edges keeps the real ratio E / V
    slots = {c: rng.choice(owners_dist) for c in companies}
    target_edges = round(n * 946 / 405)
    scale = target_edges / max(1, sum(slots.values()))
    slots = {c: max(1, round(s * scale)) for c, s in slots.items()}

    owners_of = {c: set() for c in companies}
    held_count = {h: 0 for h in holders}
    order = holders[:]
    rng.shuffle(order)
    free = [c for c in companies for _ in range(slots[c])]
    rng.shuffle(free)

    def place(company, holder):
        if holder == company or holder in owners_of[company]:
            return False
        owners_of[company].add(holder)
        if holder in held_count:
            held_count[holder] += 1
        return True

    # every non-listed holder holds at least one company
    for h in order:
        while free and not place(free.pop(), h):
            pass
    # remaining slots: another listed company, or a holder chosen by preferential attachment
    weights_pool = holders[:]
    for c in free:
        for _ in range(20):
            if rng.random() < COMPANY_HOLDER_SHARE:
                h = rng.choice(companies)
            else:
                h = rng.choice(weights_pool)
            if place(c, h):
                if h in held_count:
                    weights_pool.append(h)              # the rich get richer
                break

    for c in companies:
        owners = sorted(owners_of[c])
        stakes = [rng.choice(stakes_dist) for _ in owners]
        total, cap = sum(stakes), rng.uniform(0.5, 0.85)
        if total > cap:
            stakes = [s * cap / total for s in stakes]
        for h, s in zip(owners, stakes):
            g.add_edge(h, c, s)
    g.sort_edges()
    return g
