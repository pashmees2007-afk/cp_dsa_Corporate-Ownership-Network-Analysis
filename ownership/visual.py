"""Phase 7 - ownership sub-graphs for display.

Builds the node and edge lists the app draws, and renders them with PyVis
(vis-network). Building is plain Python and tested; rendering needs PyVis.

Encoding
  node colour + shape   entity type: listed company (blue square), other
                        corporate (orange dot), natural person (aqua
                        triangle). Shape repeats the colour, so type never
                        depends on colour alone.
  node label            the entity name, always visible
  edge width            stake
  edge label            stake, on edges of 1% or more (all stakes on hover)
  circular edge         red and dashed: an edge inside a circular-holding
                        group (Phase 5 SCC); named in the hover text
  focus                 the queried company or owner, larger with a dark ring
"""
import re
from dataclasses import dataclass, field

from .chains import ownership_chains

# Reference palette, categorical slots 1-3 (validated all-pairs) and status "critical".
COLOURS = {"listed": "#2a78d6", "corporate": "#eb6834", "individual": "#1baf7a"}
SHAPES = {"listed": "square", "corporate": "dot", "individual": "triangle"}
LABELS = {"listed": "Listed company", "corporate": "Other corporate", "individual": "Natural person"}
CIRCULAR = "#d03b3b"
EDGE = "#898781"
_REFIT = """<script>
(function () {
  function refit() { if (typeof network !== "undefined") { network.redraw(); network.fit(); } }
  window.addEventListener("load", function () { setTimeout(refit, 150); });
  window.addEventListener("resize", function () { setTimeout(refit, 50); });
})();
</script>"""
_BOOTSTRAP = re.compile(r'<(link|script)[^>]*bootstrap[^>]*>(\s*</script>)?', re.I)
INK = "#0b0b0b"
SURFACE = "#fcfcfb"


def kind(entity):
    if entity.listed:
        return "listed"
    return "individual" if entity.entity_type == "individual" else "corporate"


@dataclass
class SubGraph:
    nodes: dict = field(default_factory=dict)       # entity ID -> {"name", "kind", "note"}
    edges: dict = field(default_factory=dict)       # (holder, held) -> {"stake", "circular"}
    focus: str | None = None
    layered: bool = True                            # hierarchical layout (owners above)

    def add_node(self, entity, note=""):
        if entity.id not in self.nodes:
            self.nodes[entity.id] = {"name": entity.name, "kind": kind(entity), "note": note}
        elif note and not self.nodes[entity.id]["note"]:
            self.nodes[entity.id]["note"] = note

    def add_edge(self, holder, held, stake, circular):
        self.edges[(holder, held)] = {"stake": stake, "circular": circular}


def _group_of(groups):
    return {n: i for i, g in enumerate(groups) for n in g}


def company_subgraph(graph, company, groups, min_effective=0.0001, notes=None, max_chains=None):
    """Every entity and edge on the company's ownership chains (Phase 4)."""
    sg = SubGraph(focus=company)
    group = _group_of(groups)
    notes = notes or {}
    sg.add_node(graph.nodes[company], notes.get(company, ""))
    chains = ownership_chains(graph, company, min_effective)
    for chain in chains[:max_chains]:
        for held, holder, stake in zip(chain.nodes, chain.nodes[1:], chain.stakes):
            sg.add_node(graph.nodes[holder], notes.get(holder, ""))
            circ = holder in group and group.get(holder) == group.get(held)
            sg.add_edge(holder, held, stake, circ)
    return sg


def owner_subgraph(graph, forest, owner, groups, companies=None, notes=None):
    """The owner's tree (Phase 6 forest): the routes by which it reaches
    `companies` (default: everything it reaches). Built by walking parent
    pointers up from each company's tree nodes, so no graph traversal."""
    sg = SubGraph(focus=owner)
    group = _group_of(groups)
    notes = notes or {}
    sg.add_node(graph.nodes[owner], notes.get(owner, ""))
    if owner not in forest.roots:
        return sg
    wanted = set(forest.portfolio(owner)) if companies is None else set(companies)
    for company in sorted(wanted):
        for node in forest.index.get(company, ()):
            route, n = [], node
            while n.parent is not None:
                route.append(n)
                n = n.parent
            if n.entity != owner:
                continue                             # a node in another owner's tree
            for child in route:
                parent = child.parent.entity
                sg.add_node(graph.nodes[child.entity], notes.get(child.entity, ""))
                circ = parent in group and group.get(parent) == group.get(child.entity)
                sg.add_edge(parent, child.entity, child.stake, circ)
    return sg


def group_subgraph(graph, members):
    """All edges between the members of one circular-holding group."""
    sg = SubGraph(layered=False)
    inside = set(members)
    for n in members:
        sg.add_node(graph.nodes[n])
    for n in members:
        for e in graph.holdings(n):
            if e.held in inside:
                sg.add_edge(e.holder, e.held, e.stake, True)
    return sg


def levels(sg):
    """Row of each node in the layered drawing, by BFS from the focus. In a
    company view (edges point into the focus) the owners sit above: level =
    deepest layer - layers from the company. In an owner view the owner is on
    top: level = layers from the owner. Explicit levels keep circular edges
    from confusing the layout."""
    into, out = {}, {}
    for holder, held in sg.edges:
        into.setdefault(held, []).append(holder)
        out.setdefault(holder, []).append(held)
    upward = bool(into.get(sg.focus))
    step = into if upward else out
    dist, queue, i = {sg.focus: 0}, [sg.focus], 0
    while i < len(queue):
        v = queue[i]
        i += 1
        for w in step.get(v, ()):
            if w not in dist:
                dist[w] = dist[v] + 1
                queue.append(w)
    top = max(dist.values())
    return {n: (top - d if upward else d) for n, d in dist.items()}


def pct(x):
    return f"{x * 100:.2f}%" if x >= 0.0001 else f"{x * 100:.4f}%"


def render(sg, height=620):
    """HTML page (vis-network, inlined so it works offline) for a SubGraph."""
    from pyvis.network import Network

    net = Network(height=f"{height}px", width="100%", directed=True, bgcolor=SURFACE, font_color=INK,
                  cdn_resources="in_line")
    level = levels(sg) if sg.layered and sg.focus else {}
    for nid, n in sg.nodes.items():
        focus = nid == sg.focus
        extra = {"level": level[nid]} if nid in level else {}
        title = f"{n['name']}\n{LABELS[n['kind']]}" + (f"\n{n['note']}" if n["note"] else "")
        net.add_node(nid, label=n["name"], title=title, shape=SHAPES[n["kind"]],
                     color={"background": COLOURS[n["kind"]], "border": INK if focus else COLOURS[n["kind"]]},
                     borderWidth=4 if focus else 1, size=28 if focus else 14,
                     font={"size": 18 if focus else 13, "color": INK, "strokeWidth": 3, "strokeColor": SURFACE},
                     widthConstraint={"maximum": 125}, **extra)
    for (holder, held), e in sg.edges.items():
        width = 1 + min(6.0, e["stake"] * 12)
        net.add_edge(holder, held, title=f"{sg.nodes[holder]['name']} holds {pct(e['stake'])} of "
                                         f"{sg.nodes[held]['name']}" + (" (circular holding)" if e["circular"] else ""),
                     label=pct(e["stake"]) if e["stake"] >= 0.01 else "",
                     width=width, color=CIRCULAR if e["circular"] else EDGE, dashes=e["circular"],
                     arrows="to", font={"size": 11, "color": "#52514e", "strokeWidth": 3,
                                        "strokeColor": SURFACE, "align": "middle"})
    if sg.layered:
        net.set_options("""{
          "layout": {"hierarchical": {"enabled": true, "direction": "UD",
                                      "levelSeparation": 150, "nodeSpacing": 140}},
          "physics": {"enabled": false},
          "interaction": {"hover": true, "navigationButtons": true, "tooltipDelay": 80},
          "edges": {"smooth": {"type": "cubicBezier", "forceDirection": "vertical", "roundness": 0.4}}
        }""")
    else:
        net.set_options("""{
          "physics": {"solver": "forceAtlas2Based",
                      "forceAtlas2Based": {"gravitationalConstant": -120, "springLength": 200},
                      "stabilization": {"iterations": 300}},
          "interaction": {"hover": true, "navigationButtons": true, "tooltipDelay": 80},
          "edges": {"smooth": {"type": "curvedCW", "roundness": 0.15}}
        }""")
    html = net.generate_html(notebook=False)
    # PyVis also links Bootstrap from a CDN for menus this page does not use;
    # dropping it keeps the page fully offline.
    # Re-fit once loaded and whenever the frame is resized: a graph drawn in a
    # hidden tab is laid out at zero width and would otherwise stay off-screen.
    html = html.replace("</body>", _REFIT + "</body>")
    return _BOOTSTRAP.sub("", html)
