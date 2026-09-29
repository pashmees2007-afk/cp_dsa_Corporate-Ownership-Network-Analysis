"""Phase 4 - query interface: company name in, ownership chains out.

    python -m ownership.query "tata steel"
    python -m ownership.query "hindalco" --top 20 --min-stake 0.1
    python -m ownership.query --report      # chains for every listed company -> data/

The name is matched with the Phase 3 index (exact, then prefix, then near
match), so "tata steel", "TATA STEEL LIMITED" and "tata stel" all find Tata
Steel Ltd.
"""
import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .chains import MIN_EFFECTIVE, iter_chains, ownership_chains, ultimate_owners
from .graph import OwnershipGraph
from .ingest import read_records
from .resolve import build_index

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "ownership_relations.csv"
END_LABELS = {"natural_person": "natural person", "no_recorded_owner": "no recorded owner",
              "circular": "CIRCULAR", "below_threshold": "below threshold"}


@dataclass
class Pipeline:
    records: list
    index: object                # EntityIndex
    graph: OwnershipGraph


def load(path=DATASET):
    """Phases 2-4 end to end: ingest, resolve, build the graph."""
    records = read_records(path).records
    index = build_index(records)
    return Pipeline(records, index, OwnershipGraph.from_records(records, index))


def pct(x):
    return f"{x * 100:.2f}%" if x >= 0.0001 else f"{x * 100:.4f}%"


def format_chain(graph, chain):
    parts = [graph.nodes[chain.nodes[0]].name]
    for node, stake in zip(chain.nodes[1:], chain.stakes):
        parts.append(f"<-[{pct(stake)}]- {graph.nodes[node].name}")
    return " ".join(parts)


def describe(p, query, top=10, min_effective=MIN_EFFECTIVE, out=sys.stdout):
    """Print the ownership report for the best match of `query`. Returns the chains."""
    matches = p.index.lookup(query)
    if not matches:
        print(f"No entity matches {query!r}.", file=out)
        return []
    entity = matches[0]
    g = p.graph
    kind = "listed company" if entity.listed else entity.entity_type
    print(f"{entity.name}  [{entity.id}, {kind}]", file=out)
    if len(matches) > 1:
        print("  other matches: " + "; ".join(m.name for m in matches[1:]), file=out)

    if not g.owners(entity.id):
        print("\nNo recorded owners: this entity files no shareholding pattern in the dataset.", file=out)
        holdings = g.holdings(entity.id)
        if holdings:
            print(f"It holds shares in {len(holdings)} listed compan{'y' if len(holdings) == 1 else 'ies'}:", file=out)
            for e in holdings:
                print(f"  {pct(e.stake):>8}  {g.nodes[e.held].name}", file=out)
        return []

    chains = ownership_chains(g, entity.id, min_effective)
    ends = Counter(c.end for c in chains)
    print(f"\n{len(chains)} ownership chains with effective stake >= {pct(min_effective)} "
          f"({', '.join(f'{n} {END_LABELS[e]}' for e, n in ends.most_common())})", file=out)
    print(f"\nTop {min(top, len(chains))} by effective stake:", file=out)
    for i, c in enumerate(chains[:top], 1):
        print(f"{i:3}. {pct(c.effective):>8}  {c.layers} layer{'s' if c.layers > 1 else ' '}  "
              f"[{END_LABELS[c.end]}]", file=out)
        print(f"       {format_chain(g, c)}", file=out)

    owners = ultimate_owners(chains)
    if owners:
        print(f"\nUltimate owners (effective stakes summed over routes; top {min(top, len(owners))}):", file=out)
        for ent, total, n in owners[:top]:
            e = g.nodes[ent]
            print(f"  {pct(total):>8}  {e.name}  ({e.entity_type}{', ' + str(n) + ' routes' if n > 1 else ''})",
                  file=out)
        people = [(ent, total) for ent, total, _ in owners if g.nodes[ent].entity_type == "individual"]
        if people:
            ent, total = people[0]
            print(f"\nLargest natural-person owner: {g.nodes[ent].name} ({pct(total)})", file=out)
        else:
            print("\nNo chain reaches a natural person: every chain ends at an entity whose own "
                  "owners are not in the dataset.", file=out)
    circular = [c for c in chains if c.end == "circular"]
    if circular:
        print(f"\nCircular holdings on {len(circular)} chain(s), e.g.:\n       {format_chain(g, circular[0])}",
              file=out)
    return chains


def write_report(p, min_effective=MIN_EFFECTIVE):
    """Chains for every listed company: data/ownership_chains.csv and data/chains_report.json."""
    g = p.graph
    listed = sorted((e for e in p.index.entities if e.listed), key=lambda e: e.name.casefold())
    rows, companies = [], []
    for company in listed:
        chains = ownership_chains(g, company.id, min_effective)
        for rank, c in enumerate(chains, 1):
            rows.append({"company_id": company.id, "company": company.name, "rank": rank,
                         "effective_pct": round(c.effective * 100, 6), "layers": c.layers, "end": c.end,
                         "terminal_id": c.terminal, "terminal": g.nodes[c.terminal].name,
                         "chain": format_chain(g, c), "chain_ids": ">".join(c.nodes)})
        owners = ultimate_owners(chains)
        people = [o for o in owners if g.nodes[o[0]].entity_type == "individual"]
        companies.append({
            "id": company.id, "company": company.name, "chains": len(chains),
            "chains_by_end": dict(Counter(c.end for c in chains)),
            "max_layers": max((c.layers for c in chains), default=0),
            "top_ultimate_owner": {"name": g.nodes[owners[0][0]].name, "entity_type": g.nodes[owners[0][0]].entity_type,
                                   "effective_pct": round(owners[0][1] * 100, 4)} if owners else None,
            "largest_natural_person": {"name": g.nodes[people[0][0]].name,
                                       "effective_pct": round(people[0][1] * 100, 4)} if people else None,
        })
    with open(ROOT / "data" / "ownership_chains.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    unthresholded = sum(1 for c in listed for _ in iter_chains(g, c.id, 0.0))
    report = {
        "graph": {"nodes": len(g), "edges": g.edge_count,
                  "nodes_with_owners": sum(1 for n in g.nodes if g.owners(n)),
                  "density": round(g.edge_count / (len(g) * (len(g) - 1)), 5)},
        "min_effective_pct": min_effective * 100,
        "chains": len(rows),
        "chains_without_threshold": unthresholded,
        "chains_by_end": dict(Counter(r["end"] for r in rows)),
        "max_layers": max(r["layers"] for r in rows),
        "companies_reaching_a_natural_person": sum(c["largest_natural_person"] is not None for c in companies),
        "companies": companies,
    }
    (ROOT / "data" / "chains_report.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ownership.query", description=__doc__.split("\n\n")[0])
    ap.add_argument("company", nargs="?", help="company name (any spelling)")
    ap.add_argument("--top", type=int, default=10, help="chains and owners to show (default 10)")
    ap.add_argument("--min-stake", type=float, default=MIN_EFFECTIVE * 100,
                    help="minimum effective stake of a chain, in percent (default 0.01)")
    ap.add_argument("--report", action="store_true", help="write chains for all listed companies to data/")
    args = ap.parse_args(argv)
    if not args.company and not args.report:
        ap.error("give a company name or --report")
    p = load()
    if args.report:
        r = write_report(p, args.min_stake / 100)
        print(json.dumps({k: v for k, v in r.items() if k != "companies"}, indent=2))
    if args.company:
        describe(p, args.company, args.top, args.min_stake / 100)


if __name__ == "__main__":
    main()
