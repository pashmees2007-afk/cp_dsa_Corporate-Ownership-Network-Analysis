"""Phase 5 - cycle and structure detection.

    python -m ownership.structure       # anomaly report -> data/anomaly_report.json

Four analyses over the ownership graph (edges holder -> held):

  find_back_edges()        DFS with white/grey/black colouring. A grey vertex
                           is on the recursion stack, so an edge into a grey
                           vertex is a back edge and closes a cycle. The graph
                           has a cycle exactly when some back edge exists.
  tarjan_scc()             Tarjan's algorithm: strongly connected components in
                           one O(V + E) pass. Every component with two or more
                           companies is a circular-holding group: each member
                           holds, directly or through the others, a stake in
                           every other member.
  bfs_levels()             BFS in level order over owner edges: the minimum
                           number of ownership layers from a company to each
                           of its direct and indirect owners. Control depth is
                           the level of the company's controller.
  connected_components()   Component labelling over the undirected projection:
                           corporate families.

All four are iterative (explicit stack or queue), O(V + E) time and O(V)
extra space.
"""
import json
import sys
from collections import Counter, deque
from pathlib import Path

from .chains import ownership_chains, ultimate_owners

ROOT = Path(__file__).resolve().parent.parent
WHITE, GREY, BLACK = 0, 1, 2
PROMOTER_ROLES = frozenset({"Promoter", "Promoter Group"})


# ---------------------------------------------------------------- cycles: DFS

def find_back_edges(graph):
    """[(holder, held, cycle)] for every back edge found by a DFS over the
    whole graph. `cycle` is the loop the back edge closes, as entity IDs from
    `held` round to `held` again, read off the DFS stack.

    Which edges are back edges depends on the DFS order (here: vertices by ID,
    edges by stake), but their existence does not: zero back edges <=> acyclic.
    """
    colour = {n: WHITE for n in graph.nodes}
    found = []
    for root in sorted(graph.nodes):
        if colour[root] != WHITE:
            continue
        colour[root] = GREY
        stack = [(root, iter(graph.holdings(root)))]
        position = {root: 0}                       # vertex -> index on the stack
        while stack:
            v, edges = stack[-1]
            edge = next(edges, None)
            if edge is None:                       # all successors done
                colour[v] = BLACK
                del position[v]
                stack.pop()
                continue
            w = edge.held
            if colour[w] == WHITE:
                colour[w] = GREY
                position[w] = len(stack)
                stack.append((w, iter(graph.holdings(w))))
            elif colour[w] == GREY:                # w is on the recursion stack: back edge
                cycle = [n for n, _ in stack[position[w]:]] + [w]
                found.append((v, w, cycle))
            # BLACK: forward or cross edge, no cycle through it
    return found


# ---------------------------------------------------------------- cycles: Tarjan

def tarjan_scc(graph):
    """Strongly connected components, in the order Tarjan's algorithm
    completes them (reverse topological order of the condensation).

    index[v]  order in which the DFS first reached v
    low[v]    smallest index reachable from v's DFS subtree using at most one
              edge back into a vertex still on the component stack
    v roots a component when low[v] == index[v]; the component is everything
    above v on the component stack.
    """
    index, low = {}, {}
    comp_stack, on_stack = [], set()
    components = []
    counter = 0
    for root in sorted(graph.nodes):
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        comp_stack.append(root)
        on_stack.add(root)
        work = [(root, iter(graph.holdings(root)))]
        while work:
            v, edges = work[-1]
            edge = next(edges, None)
            if edge is not None:
                w = edge.held
                if w not in index:                 # tree edge: descend
                    index[w] = low[w] = counter
                    counter += 1
                    comp_stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(graph.holdings(w))))
                elif w in on_stack:                # edge into the current component
                    low[v] = min(low[v], index[w])
                continue
            work.pop()                             # v finished
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = comp_stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                components.append(sorted(comp))
    return components


def circular_groups(graph):
    """Strongly connected components with two or more members, largest first."""
    return sorted((c for c in tarjan_scc(graph) if len(c) > 1), key=lambda c: (-len(c), c))


# ---------------------------------------------------------------- BFS

def bfs_levels(graph, company):
    """{entity ID: layers} for the company (0) and every direct or indirect
    owner, by BFS over inbound edges. Level k holds the entities whose
    shortest ownership route to the company has k edges."""
    level = {company: 0}
    queue = deque([company])
    while queue:
        v = queue.popleft()
        for edge in graph.owners(v):
            if edge.holder not in level:
                level[edge.holder] = level[v] + 1
                queue.append(edge.holder)
    return level


def controller(graph, company):
    """(entity ID, effective stake, highest-stake chain to it) for the ultimate
    owner with the largest effective stake (Phase 4 chains), or None."""
    chains = ownership_chains(graph, company)
    owners = ultimate_owners(chains)
    if not owners:
        return None
    ent, total, _ = owners[0]
    return ent, total, next(c for c in chains if c.terminal == ent)


# ---------------------------------------------------------------- components

def is_promoter_edge(edge):
    return any(r.holder_role in PROMOTER_ROLES for r in edge.records)


def connected_components(graph, edge_filter=None):
    """Label the components of the undirected projection of the graph.

    Vertices are numbered 0..V-1 (sorted IDs); `label` is an array with one
    component number per vertex, -1 while unvisited, so the visited set and
    the component IDs are the same array. Edges for which edge_filter returns
    False are left out. Returns (label by entity ID, components largest first).
    """
    ids = sorted(graph.nodes)
    number = {n: i for i, n in enumerate(ids)}
    label = [-1] * len(ids)
    components = []
    for start in range(len(ids)):
        if label[start] != -1:
            continue
        c = len(components)
        label[start] = c
        members, stack = [], [start]
        while stack:
            i = stack.pop()
            members.append(ids[i])
            node = ids[i]
            for edge in graph.holdings(node) + graph.owners(node):
                if edge_filter is not None and not edge_filter(edge):
                    continue
                j = number[edge.held if edge.holder == node else edge.holder]
                if label[j] == -1:
                    label[j] = c
                    stack.append(j)
        components.append(sorted(members))
    components.sort(key=lambda m: (-len(m), m))
    by_id = {n: i for i, comp in enumerate(components) for n in comp}
    return by_id, components


# ---------------------------------------------------------------- anomaly report

def _pct(x):
    return round(x * 100, 4)


def anomaly_report(p):
    """Circular holdings, deep chains and corporate families for a Pipeline."""
    g = p.graph
    name = lambda n: g.nodes[n].name                      # noqa: E731
    group_of = {p.index.entity_of(r.held_name, "corporate").id: r.group for r in p.records}
    listed = sorted((e.id for e in p.index.entities if e.listed), key=lambda n: name(n).casefold())

    # circular holdings
    back = find_back_edges(g)
    groups = []
    for k, comp in enumerate(circular_groups(g), 1):
        members = set(comp)
        internal = sorted(((e.holder, e.held, e.stake) for n in comp for e in g.holdings(n) if e.held in members),
                          key=lambda t: -t[2])
        examples = []
        for holder, held, cycle in back:
            if held in members:
                strength = 1.0
                for a, b in zip(cycle, cycle[1:]):
                    strength *= next(e.stake for e in g.holdings(a) if e.held == b)
                examples.append({"cycle": [name(n) for n in cycle], "loop_stake_pct": _pct(strength)})
        stake = {(a, b): s for a, b, s in internal}
        mutual = sorted(((a, b, s * stake[(b, a)]) for (a, b), s in stake.items() if (b, a) in stake and a < b),
                        key=lambda t: -t[2])
        groups.append({
            "id": k, "size": len(comp), "members": sorted(name(n) for n in comp),
            "groups": sorted({group_of[n] for n in comp if n in group_of}),
            "internal_edges": len(internal),
            "max_internal_stake_pct": _pct(internal[0][2]),
            "all_internal_stakes_below_0_01_pct": internal[0][2] < 0.0001,
            "strongest_edges": [{"holder": name(a), "held": name(b), "stake_pct": _pct(s)} for a, b, s in internal[:5]],
            "mutual_holdings": [{"pair": [name(a), name(b)], "stakes_pct": [_pct(stake[(a, b)]), _pct(stake[(b, a)])],
                                 "loop_stake_pct": _pct(x)} for a, b, x in mutual],
            "back_edges_found": len(examples),
            "example_cycles": sorted(examples, key=lambda x: -x["loop_stake_pct"])[:5],
        })

    # control depth
    depth = []
    for c in listed:
        levels = bfs_levels(g, c)
        ctrl = controller(g, c)
        row = {"company": name(c), "group": group_of.get(c), "owners_reachable": len(levels) - 1,
               "ownership_depth": max(levels.values())}
        if ctrl:
            ent, total, chain = ctrl
            row.update({"controller": name(ent), "controller_type": g.nodes[ent].entity_type,
                        "controller_effective_pct": _pct(total), "control_depth": levels[ent],
                        "dominant_route_layers": chain.layers,
                        "dominant_route": [name(n) for n in chain.nodes]})
        depth.append(row)
    deep = sorted((r for r in depth if r.get("control_depth", 0) >= 2),
                  key=lambda r: (-r["control_depth"], -r["dominant_route_layers"], r["company"]))

    # families
    _, all_comps = connected_components(g)
    fam_of, fams = connected_components(g, is_promoter_edge)
    families = []
    for k, comp in enumerate(c for c in fams if len(c) > 1):
        cos = [n for n in comp if g.nodes[n].listed]
        families.append({"id": k + 1, "size": len(comp),
                         "listed_companies": sorted(name(n) for n in cos),
                         "groups": dict(Counter(group_of[n] for n in cos)),
                         "natural_persons": sum(g.nodes[n].entity_type == "individual" for n in comp)})

    return {
        "summary": {
            "circular_groups": len(groups),
            "companies_in_circular_groups": sum(x["size"] for x in groups),
            "back_edges_found": len(back),
            "acyclic": not back,
            "indirectly_controlled_companies": len(deep),
            "control_depth_distribution": dict(sorted(Counter(r["control_depth"] for r in depth if "control_depth" in r).items())),
            "ownership_depth_distribution": dict(sorted(Counter(r["ownership_depth"] for r in depth).items())),
            "components_all_edges": [len(c) for c in all_comps],
            "families_promoter_edges": len(families),
            "entities_outside_families": sum(1 for c in fams if len(c) == 1),
        },
        "circular_holdings": groups,
        "deep_chains": deep,
        "control_depth": depth,
        "families": families,
    }


def print_summary(r, out=sys.stdout):
    s = r["summary"]
    print(f"Circular holdings: {s['circular_groups']} groups, {s['companies_in_circular_groups']} companies, "
          f"{s['back_edges_found']} back edges", file=out)
    for x in r["circular_holdings"]:
        flag = "  (all internal stakes < 0.01%)" if x["all_internal_stakes_below_0_01_pct"] else ""
        print(f"  #{x['id']} {x['size']} companies, strongest internal stake {x['max_internal_stake_pct']}%{flag}",
              file=out)
        print("     " + ", ".join(x["members"]), file=out)
        if x["example_cycles"]:
            ex = x["example_cycles"][0]
            print(f"     e.g. {' -> '.join(ex['cycle'])}  (loop {ex['loop_stake_pct']}%, a DFS back edge)", file=out)
    print(f"\nControl depth (BFS layers to the controller): {s['control_depth_distribution']}", file=out)
    print(f"Indirectly controlled (2+ layers): {s['indirectly_controlled_companies']}", file=out)
    for d in r["deep_chains"]:
        print(f"  {d['company']}: {' <- '.join(d['dominant_route'])} "
              f"({d['controller_effective_pct']}%; control depth {d['control_depth']}, "
              f"this route {d['dominant_route_layers']} layers)", file=out)
    print(f"\nFamilies (promoter-register edges): {s['families_promoter_edges']}; "
          f"over all edges the projection has components of sizes {s['components_all_edges']}", file=out)
    for f in r["families"]:
        print(f"  F{f['id']}: {f['size']} entities, {len(f['listed_companies'])} listed, groups {f['groups']}, "
              f"{f['natural_persons']} natural persons", file=out)


def main():
    from .query import load
    report = anomaly_report(load())
    (ROOT / "data" / "anomaly_report.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print_summary(report)


if __name__ == "__main__":
    main()
