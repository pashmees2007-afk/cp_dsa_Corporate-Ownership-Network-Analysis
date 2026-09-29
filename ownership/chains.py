"""Phase 4 - ownership chain traversal.

    chains = ownership_chains(graph, company_id)
    chains[0].nodes       # (company, owner, owner's owner, ..., terminal)
    chains[0].effective   # product of the stakes along the chain

A chain starts at the queried company and follows inbound edges (from a
company to a shareholder of it) until it reaches:

    natural_person      an entity typed individual (people, and HUFs as in Phase 1)
    no_recorded_owner   an entity with no inbound edge: unlisted companies,
                        trusts, funds and governments file no shareholding
                        pattern, so the data says nothing about their owners
    circular            the next owner is already on the chain (circular
                        shareholding). The chain ends by repeating that entity,
                        so the loop is visible; no owner can be resolved
                        along it. Phase 5 detects these structures properly.
    below_threshold     the entity has owners, but every chain through them
                        falls below min_effective

Multi-parent case: a company with several shareholders has one chain per
route, and all of them are returned, ranked by effective stake. The
effective stake of a chain is the product of the stakes along it: if A
holds 50% of B and B holds 40% of C, A's stake in C through B is 20%.

min_effective (default 0.01%) drops chains whose effective stake is below
it. It is needed, not cosmetic: the Tata companies hold stakes in each other
in loops, and without a threshold the 46 listed companies have 313,822
simple ownership chains, up to 14 layers long. At 0.01% there are 1,570,
at most 4 layers long.

Traversal is depth-first with an explicit stack. The stack holds one frame
per entity on the current chain, and each frame keeps the iterator over that
entity's inbound edges. So the chain from the queried company to the current
entity is always the list of frames on the stack, and every chain can be
recovered in full, not just its terminal entity. Each stack operation is
O(1); the total work is proportional to the number of chains produced times
their length. Enumerating chains cannot be O(V + E) in general, because the
number of chains can grow exponentially with the number of loops. The
single-visit traversal, reachable_owners(), is O(V + E).
"""
from dataclasses import dataclass

NATURAL_PERSON = "natural_person"
NO_RECORDED_OWNER = "no_recorded_owner"
CIRCULAR = "circular"
BELOW_THRESHOLD = "below_threshold"
MIN_EFFECTIVE = 0.0001               # 0.01%


@dataclass(frozen=True, slots=True)
class Chain:
    nodes: tuple                     # entity IDs, queried company first
    stakes: tuple                    # stakes[i] = stake of nodes[i + 1] in nodes[i]
    effective: float                 # product of stakes
    end: str                         # why the chain stops (see module docstring)

    @property
    def terminal(self):
        return self.nodes[-1]

    @property
    def layers(self):
        """Ownership layers between the company and the terminal entity."""
        return len(self.stakes)


def iter_chains(graph, company, min_effective=MIN_EFFECTIVE):
    """Yield every ownership chain of `company` in depth-first order."""
    if not graph.owners(company):
        return
    nodes, stakes, effective = [company], [], [1.0]
    on_chain = {company}
    frames = [[iter(graph.owners(company)), False]]   # [owner-edge iterator, produced anything?]

    while frames:
        frame = frames[-1]
        edge = next(frame[0], None)

        if edge is None:                               # every owner of nodes[-1] explored
            frames.pop()
            if not frame[1] and len(nodes) > 1:        # owners exist but none got through
                yield Chain(tuple(nodes), tuple(stakes), effective[-1], BELOW_THRESHOLD)
            on_chain.discard(nodes.pop())
            effective.pop()
            if stakes:
                stakes.pop()
            continue

        eff = effective[-1] * edge.stake
        if eff < min_effective:
            continue
        owner = edge.holder

        if owner in on_chain:                          # loop back onto the chain
            frame[1] = True
            yield Chain(tuple(nodes) + (owner,), tuple(stakes) + (edge.stake,), eff, CIRCULAR)
            continue

        entity = graph.nodes[owner]
        if entity.entity_type == "individual" or not graph.owners(owner):
            frame[1] = True
            end = NATURAL_PERSON if entity.entity_type == "individual" else NO_RECORDED_OWNER
            yield Chain(tuple(nodes) + (owner,), tuple(stakes) + (edge.stake,), eff, end)
            continue

        frame[1] = True                                # descend: owner has owners of its own
        nodes.append(owner)
        stakes.append(edge.stake)
        effective.append(eff)
        on_chain.add(owner)
        frames.append([iter(graph.owners(owner)), False])


def ownership_chains(graph, company, min_effective=MIN_EFFECTIVE):
    """All chains of `company`, highest effective stake first (then shorter first)."""
    return sorted(iter_chains(graph, company, min_effective),
                  key=lambda c: (-c.effective, c.layers, c.nodes))


def ultimate_owners(chains):
    """Aggregate chains by terminal entity.

    Returns [(entity ID, total effective stake, number of chains)] for chains
    that end at a natural person or an entity with no recorded owner, largest
    first. Summing over routes is exact when the routes contain no loop;
    where loops exist the simple-chain sum is a lower bound (Phase 6 computes
    the full value with matrices).
    """
    totals = {}
    for c in chains:
        if c.end in (NATURAL_PERSON, NO_RECORDED_OWNER):
            t, n = totals.get(c.terminal, (0.0, 0))
            totals[c.terminal] = (t + c.effective, n + 1)
    return sorted(((e, t, n) for e, (t, n) in totals.items()), key=lambda x: (-x[1], x[0]))


def reachable_owners(graph, company):
    """Every entity with a direct or indirect stake in `company`: one
    depth-first pass with a visited set and an explicit stack, O(V + E)."""
    seen, stack = {company}, [company]
    while stack:
        node = stack.pop()
        for edge in graph.owners(node):
            if edge.holder not in seen:
                seen.add(edge.holder)
                stack.append(edge.holder)
    seen.discard(company)
    return seen
