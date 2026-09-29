"""Phase 7 - Beneficial Ownership Explorer (Streamlit app).

    pip install -r requirements.txt
    streamlit run app.py

Three views over the pipeline built in Phases 2-6:
  Company     name in -> ranked ownership chains, ultimate owners, and the
              ownership sub-graph with circular holdings highlighted
  Owner       everything one owner reaches (the Phase 6 owner trees)
  Anomalies   circular-holding groups, indirectly controlled companies and
              family control concentration
"""
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ownership.chains import ownership_chains, ultimate_owners
from ownership.control import ControlModel, analyse
from ownership.forest import OwnershipForest
from ownership.query import END_LABELS, format_chain, load
from ownership.structure import anomaly_report, bfs_levels, circular_groups
from ownership.visual import (CIRCULAR, COLOURS, LABELS, company_subgraph, group_subgraph, owner_subgraph,
                              pct, render)

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Beneficial Ownership Explorer", layout="wide")


@st.cache_resource(show_spinner="Building the ownership graph…")
def state():
    p = load()
    g = p.graph
    control, _ = analyse(p)
    listed = sorted((e for e in p.index.entities if e.listed), key=lambda e: e.name.casefold())
    forest = OwnershipForest.from_chains(ch for e in listed for ch in ownership_chains(g, e.id))
    return {
        "p": p, "g": g, "model": ControlModel(g), "groups": circular_groups(g),
        "anomaly": anomaly_report(p), "control": control, "forest": forest, "listed": listed,
        "company_metrics": {m["company"]: m for m in control["companies"]},
        "er": json.loads((ROOT / "data" / "er_evaluation.json").read_text("utf-8")),
    }


S = state()
g, p = S["g"], S["p"]


def legend():
    items = [f'<span style="color:{COLOURS[k]};font-size:1.1em">{sym}</span> {LABELS[k]}'
             for k, sym in (("listed", "■"), ("corporate", "●"), ("individual", "▲"))]
    items.append(f'<span style="color:{CIRCULAR};font-weight:700">- - →</span> Circular holding (inside a Phase 5 group)')
    items.append("Arrow: holder → company held · width: stake · hover a node or edge for details")
    items.append("scroll to zoom, drag to pan")
    st.markdown(" &nbsp;·&nbsp; ".join(items), unsafe_allow_html=True)


def show_graph(sg, height=620):
    if not sg.edges:
        st.info("Nothing to draw at this threshold.")
        return
    components.html(render(sg, height), height=height + 20, scrolling=False)
    legend()


def group_of(entity_id):
    return next((grp for grp in S["groups"] if entity_id in grp), None)


tab_company, tab_owner, tab_anomalies, tab_about = st.tabs(["Company", "Owner", "Anomalies", "About the data"])

# ---------------------------------------------------------------- company
with tab_company:
    st.subheader("Who owns this company?")
    c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
    names = [e.name for e in S["listed"]]
    picked = c1.selectbox("Listed company", names, index=names.index("Tata Steel Ltd"))
    typed = c2.text_input("…or type any name (any spelling)", placeholder="e.g. hindalco, TATA STEL, M M Muthiah")
    stake_opts = [0.01, 0.1, 0.5, 1.0, 5.0]
    min_stake = c3.select_slider("Minimum effective stake (%)", stake_opts, value=0.01)
    top_n = c4.slider("Chains drawn", 5, 100, 12, help="The graph draws the top chains; the table lists all.")

    entity = next(e for e in S["listed"] if e.name == picked)
    if typed.strip():
        matches = p.index.lookup(typed)
        if not matches:
            st.warning(f"No entity matches “{typed}”.")
            st.stop()
        entity = matches[0]
        if len(matches) > 1:
            st.caption("Matched **" + entity.name + "** · other matches: " + "; ".join(m.name for m in matches[1:]))

    if not g.owners(entity.id):
        st.markdown(f"### {entity.name}")
        st.info("No recorded owners: this entity files no shareholding pattern, so its own owners are not in "
                "the data. Its holdings are shown instead; the **Owner** tab shows everything it reaches.")
        st.dataframe(pd.DataFrame([{"Company": g.nodes[e.held].name, "Stake": round(e.stake * 100, 4)}
                                   for e in g.holdings(entity.id)]), hide_index=True, width="stretch")
        show_graph(owner_subgraph(g, S["forest"], entity.id, S["groups"]))
        st.stop()

    chains = ownership_chains(g, entity.id, min_stake / 100)
    owners = ultimate_owners(chains)
    exact = S["model"].integrated(entity.id)
    metrics = S["company_metrics"].get(entity.name)
    st.markdown(f"### {entity.name}")
    m1, m2, m3, m4, m5 = st.columns(5)
    if owners:
        ctrl = owners[0][0]
        m1.markdown(f'<div style="font-size:0.875rem">Controller</div>'
                    f'<div style="font-size:1.35rem;font-weight:600;line-height:1.3">{g.nodes[ctrl].name}</div>',
                    unsafe_allow_html=True)
        m2.metric("Controller's integrated stake", pct(exact.get(ctrl, 0.0)),
                  help="Every route, including those round circular holdings (Phase 6)")
        m3.metric("Control depth", f"{bfs_levels(g, entity.id)[ctrl]} layer(s)", help="BFS minimum (Phase 5)")
    if metrics:
        m4.metric("Family stake", f"{metrics['family_pct']:.2f}%", help=f"Promoter family {metrics['family']}")
        m5.metric("Traced to named owners", f"{metrics['traced_pct']:.1f}%",
                  help="The rest is public holdings below 1%, which filings do not name")
    grp = group_of(entity.id)
    if grp:
        st.warning("⚠ Circular holding: part of a group of "
                   f"{len(grp)} companies that hold each other: " + ", ".join(g.nodes[n].name for n in grp if n != entity.id))

    show_graph(company_subgraph(g, entity.id, S["groups"], min_stake / 100, max_chains=top_n))

    left, right = st.columns([3, 2])
    with left:
        st.markdown(f"**{len(chains)} ownership chains**, ranked by effective stake")
        st.dataframe(pd.DataFrame([{"#": i, "Effective %": round(c.effective * 100, 4), "Layers": c.layers,
                                    "Ends at": END_LABELS[c.end], "Chain": format_chain(g, c)}
                                   for i, c in enumerate(chains, 1)]),
                     hide_index=True, width="stretch", height=420)
    with right:
        st.markdown("**Ultimate owners**: integrated stake (all routes) vs simple chains")
        rows = []
        for ent, total, n in owners:
            rows.append({"Owner": g.nodes[ent].name, "Type": g.nodes[ent].entity_type,
                         "Integrated %": round(exact.get(ent, 0.0) * 100, 4),
                         "Simple chains %": round(total * 100, 4), "Routes": n})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=420)

# ---------------------------------------------------------------- owner
with tab_owner:
    st.subheader("What does this owner reach?")
    forest = S["forest"]
    roots = sorted(forest.roots, key=lambda o: (-len(forest.portfolio(o)), g.nodes[o].name))
    labels = [g.nodes[o].name for o in roots]
    default = labels.index("Tata Sons Private Limited")
    oc1, oc2 = st.columns([4, 1])
    owner_name = oc1.selectbox("Beneficial owner (a person, or an entity with no recorded owner)", labels,
                               index=default)
    owner = roots[labels.index(owner_name)]
    portfolio = forest.portfolio(owner)
    top_c = oc2.slider("Companies drawn", 1, max(1, len(portfolio)), min(10, len(portfolio)),
                       help="Routes to the owner's largest holdings; the table lists all.")
    drawn = sorted(portfolio, key=lambda c: -portfolio[c])[:top_c]
    controlled = [m["company"] for m in S["control"]["companies"] if m["controller"] == owner_name]
    o1, o2, o3 = st.columns(3)
    o1.metric("Listed companies reached", len(portfolio))
    o2.metric("Of which it is the controller", len(controlled))
    o3.metric("Type", g.nodes[owner].entity_type)
    show_graph(owner_subgraph(g, forest, owner, S["groups"], companies=drawn), height=660)
    st.dataframe(pd.DataFrame(sorted(
        ({"Company": g.nodes[c].name,
          "Integrated %": round(S["model"].integrated(c).get(owner, 0.0) * 100, 4),
          "Simple chains %": round(s * 100, 4),
          "Controller": "yes" if g.nodes[c].name in controlled else ""} for c, s in portfolio.items()),
        key=lambda r: -r["Integrated %"])), hide_index=True, width="stretch")
    st.caption("Built from the Phase 6 owner trees: the answer comes from walking one tree, without traversing "
               "the graph. Chains below the 0.01% default threshold are not stored.")

# ---------------------------------------------------------------- anomalies
with tab_anomalies:
    A, C = S["anomaly"], S["control"]
    s = A["summary"]
    st.subheader("Anomaly dashboard")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Circular-holding groups", s["circular_groups"])
    t2.metric("Companies in them", s["companies_in_circular_groups"])
    t3.metric("Indirectly controlled companies", s["indirectly_controlled_companies"])
    t4.metric("Corporate families", s["families_promoter_edges"])

    st.markdown("#### ⚠ Circular holdings")
    st.caption("Strongly connected components (Tarjan). Every member holds, directly or through the others, "
               "a stake in every other member. Loop stake = product of the stakes round the loop.")
    self_own = {m["company"]: m["self_ownership_pct"] for m in C["companies"]}
    for grp_info, members in zip(A["circular_holdings"], S["groups"]):
        title = f"Group {grp_info['id']}: {grp_info['size']} companies, strongest internal stake " \
                f"{grp_info['max_internal_stake_pct']}%"
        if grp_info["all_internal_stakes_below_0_01_pct"]:
            title += " (all internal stakes round to 0.00%)"
        with st.expander(title, expanded=grp_info["id"] == 1):
            a, b = st.columns([3, 2])
            with a:
                show_graph(group_subgraph(g, members), height=520)
            with b:
                st.markdown("**Mutual holdings** (pairs that hold each other)")
                st.dataframe(pd.DataFrame([{"Pair": " ↔ ".join(m["pair"]),
                                            "Stakes %": " / ".join(str(x) for x in m["stakes_pct"]),
                                            "Loop %": m["loop_stake_pct"]} for m in grp_info["mutual_holdings"]]),
                             hide_index=True, width="stretch")
                st.markdown("**Indirect stake in itself** (Phase 6)")
                st.dataframe(pd.DataFrame([{"Company": n, "Self-ownership %": round(self_own.get(n, 0.0), 4)}
                                           for n in grp_info["members"]]), hide_index=True, width="stretch")

    st.markdown("#### Deep chains: indirectly controlled companies")
    st.caption("The controller holds no shares of the company itself and controls it through another listed "
               "company. Control depth = BFS minimum layers; the route shown is the one carrying the most stake.")
    st.dataframe(pd.DataFrame([{"Company": d["company"], "Controller": d["controller"],
                                "Effective %": d["controller_effective_pct"], "Control depth": d["control_depth"],
                                "Route layers": d["dominant_route_layers"],
                                "Route": " ← ".join(d["dominant_route"])} for d in A["deep_chains"]]),
                 hide_index=True, width="stretch")

    st.markdown("#### Family control concentration")
    fam_names = {f"F{f['id']}": ", ".join(f"{k}" for k in f["groups"]) + f" (F{f['id']})" for f in A["families"]}
    fam_rows = [{"Family": fam_names.get(f, f), "Companies": m["companies"],
                 "Family stake, mean %": round(m["family_pct_mean"], 1),
                 "Median %": round(m["family_pct_median"], 1),
                 "> 50%": m["companies_family_over_50_pct"], "25–50%": m["companies_family_25_to_50_pct"],
                 "< 25%": m["companies_family_under_25_pct"], "HHI, mean": round(m["hhi_mean"]),
                 "Main controller": next(iter(m["controllers"]))} for f, m in C["families"].items()]
    st.dataframe(pd.DataFrame(fam_rows), hide_index=True, width="stretch")

    bars = pd.DataFrame([{"Company": m["company"], "Family": fam_names.get(m["family"], m["family"]),
                          "Family stake %": round(m["family_pct"], 2), "Controller": m["controller"],
                          "Controller %": round(m["controller_pct"], 2)}
                         for m in C["companies"] if m["family"] in ("F1", "F2", "F3")])
    rules = alt.Chart(pd.DataFrame({"x": [25, 50], "Threshold": ["25%: can block special resolutions",
                                                                "50%: majority"]})).mark_rule(
        color="#898781", strokeDash=[4, 3]).encode(x="x:Q", tooltip=["Threshold"])
    for fam in sorted(bars["Family"].unique()):
        rows = bars[bars["Family"] == fam]
        chart = alt.Chart(rows).mark_bar(color=COLOURS["listed"], cornerRadiusEnd=4, height={"band": 0.72}).encode(
            y=alt.Y("Company:N", sort="-x", title=None, axis=alt.Axis(labelLimit=280)),
            x=alt.X("Family stake %:Q", scale=alt.Scale(domain=[0, 100]),
                    title="Integrated stake of the promoter family (%)"),
            tooltip=["Company", "Family stake %", "Controller", "Controller %"])
        st.markdown(f"**{fam}**")
        st.altair_chart(alt.layer(chart, rules).properties(height=26 * len(rows)).configure_view(stroke=None)
                        .configure_axis(gridColor="#e1e0d9", domainColor="#c3c2b7", labelColor="#52514e",
                                        titleColor="#52514e"), width="stretch")
    st.caption("Dashed lines: 25% (a holder above it can block special resolutions, which need 75%) and 50% "
               "(majority). Stakes are economic (integrated), not votes. Hover a bar for the controller.")

# ---------------------------------------------------------------- about
with tab_about:
    er = S["er"]["configs"]["+ fuzzy, token check (full method)"]
    st.subheader("About the data and the pipeline")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Ownership records", len(p.records))
    a2.metric("Entities (graph nodes)", len(p.index))
    a3.metric("Ownership edges", g.edge_count)
    a4.metric("Entity resolution P / R", f"{er['precision']:.2f} / {er['recall']:.2f}")
    st.markdown("""
| Phase | What it does | Details |
|---|---|---|
| 1 | BSE shareholding-pattern filings of 46 listed companies (Tata, Aditya Birla, Murugappa) | `docs/schema.md` |
| 2 | Parse, validate and normalise names | `docs/ingestion.md` |
| 3 | Entity resolution: trie, Levenshtein, capacity rules | `docs/entity_resolution.md` |
| 4 | Adjacency-list graph, chain traversal (DFS, explicit stack) | `docs/chains.md` |
| 5 | Cycles (DFS, Tarjan SCC), control depth (BFS), families (components) | `docs/structure.md` |
| 6 | Integrated stakes through loops (matrices), owner trees, family metrics | `docs/control.md` |

**Limits to keep in mind.** Chains stop at unlisted holding companies (Tata Sons, Ambadi Investments,
Birla Group Holdings), which file no shareholding pattern. Only public holders of 1% or more are named.
Stakes are economic interest, not votes.
""")
