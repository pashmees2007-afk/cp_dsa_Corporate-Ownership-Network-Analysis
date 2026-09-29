# Phase 4 — Graph Construction and Chain Traversal

Deliverable for Phase 4 of `CP_Implementation_Plan.docx`: a working query interface that accepts a company name and returns its ownership chain. This is the first end-to-end build: raw CSV → ingestion (Phase 2) → entity resolution (Phase 3) → graph → chains.

| File | Contents |
|---|---|
| [`ownership/graph.py`](../ownership/graph.py) | `OwnershipGraph`: directed weighted graph, adjacency lists |
| [`ownership/chains.py`](../ownership/chains.py) | Chain traversal (DFS, explicit stack), ranking, ultimate-owner aggregation |
| [`ownership/query.py`](../ownership/query.py) | Query interface (command line) and the all-company report |
| [`data/ownership_chains.csv`](../data/ownership_chains.csv) | Every chain of every listed company (1,570 rows) |
| [`data/chains_report.json`](../data/chains_report.json) | Per-company summary and dataset totals |

```
python -m ownership.query "tata steel"                  # any spelling: "TATA STEEL LTD", "tata stel"
python -m ownership.query "hindalco" --top 20 --min-stake 0.1
python -m ownership.query --report                      # regenerate the two data files
python -m unittest                                      # 124 tests (22 for this phase)
```

## 1. Example

```
$ python -m ownership.query hindalco --top 3
Hindalco Industries Ltd  [E0138, listed company]

43 ownership chains with effective stake >= 0.01% (36 no recorded owner, 6 natural person, 1 CIRCULAR)

Top 3 by effective stake:
  1.   15.58%  1 layer   [no recorded owner]
       Hindalco Industries Ltd <-[15.58%]- IGH Holdings Private Limited
  2.   11.38%  1 layer   [no recorded owner]
       Hindalco Industries Ltd <-[11.38%]- Birla Group Holdings Private Limited
  3.    4.59%  1 layer   [no recorded owner]
       Hindalco Industries Ltd <-[4.59%]- Life Insurance Corporation Of India

Ultimate owners (effective stakes summed over routes; top 3):
    15.84%  IGH Holdings Private Limited  (corporate, 2 routes)
    12.81%  Birla Group Holdings Private Limited  (corporate, 4 routes)
     4.85%  Life Insurance Corporation Of India  (corporate, 2 routes)

Largest natural-person owner: Kumar Mangalam Birla (0.07%)

Circular holdings on 1 chain(s), e.g.:
       Hindalco Industries Ltd <-[3.92%]- Grasim Industries Ltd <-[4.29%]- Hindalco Industries Ltd
```

For an entity with no recorded owners, such as `tata sons`, the interface lists what the entity holds instead.

## 2. Graph

| | |
|---|---|
| Nodes (Phase 3 entities) | 405 |
| Edges (holder → held, weight = stake as a fraction) | 946 |
| Nodes with at least one owner | 46 (the listed companies) |
| Density E / (V(V−1)) | 0.58% |

**Adjacency list, not matrix.** Each node has two lists: edges out (what it holds) and edges in (who holds it). Together they take O(V + E) space, about 1,900 edge entries here. An adjacency matrix would take O(V²) = 164,025 cells, of which 0.58% would be non-zero. Chain traversal only needs "the owners of X", which is a direct read of X's inbound list. Each list is sorted by stake, largest first.

If two rows resolve to the same (holder, company) pair, their stakes are added into one edge. They would be separate filings of the same owner. This does not happen in the current data (946 rows → 946 edges), and a test covers it. Self-ownership edges are rejected; Phase 2 already flags them.

## 3. Traversal

### 3.1 What a chain is

A chain starts at the queried company and follows inbound edges: from a company to one of its shareholders, then to one of *that* shareholder's shareholders, and so on. It stops at:

| End | Meaning | Chains |
|---|---|---|
| `natural_person` | an entity typed `individual` (people, and HUFs as typed in Phase 1) | 386 |
| `no_recorded_owner` | an entity with no inbound edge. Unlisted companies, trusts, funds and governments file no shareholding pattern, so the data says nothing about their owners | 1,143 |
| `circular` | the next owner is already on the chain. The chain ends by repeating that entity, so the loop shows up in the output, e.g. Hindalco ← Grasim ← Hindalco | 13 |
| `below_threshold` | the entity has owners, but every route through them falls below the minimum effective stake | 28 |

The first two are the plan's termination conditions. `circular` is needed to terminate at all, because the data contains loops. Phase 5 detects those loops properly (Tarjan's SCC).

**Effective stake** is the product of the stakes along a chain. For example, Cholamandalam Financial Holdings holds 43.74% of Cholamandalam Investment and Finance, and Ambadi Investments holds 37.69% of Cholamandalam Financial Holdings. That route gives Ambadi an effective 16.49% of Cholamandalam Investment and Finance.

**Multiple owners.** A company with several shareholders has one chain per route. All of them are returned, ranked by effective stake. `ultimate_owners()` then adds up the chains that end at the same entity: Birla Group Holdings reaches Hindalco by 4 routes, totalling 12.81%. Adding up routes is exact when the routes contain no loop. Where loops exist the total is a lower bound, because routes that go round a loop are not counted. Phase 6 computes the exact figure with matrices.

### 3.2 DFS with an explicit stack

`iter_chains()` uses no recursion. The stack holds **one frame per entity on the current chain**, and each frame keeps the iterator over that entity's owners.
- **Descending** (the owner has owners of its own): push a frame.
- **All owners of an entity explored:** pop its frame.
- **Owner already on the chain:** emit a `circular` chain and do not descend. A set of the entities on the chain makes this check O(1).

So the stack always holds the full chain from the queried company to the current entity. The plan asks for this so that the traversal path can be recovered, not only the terminal node: every emitted chain is read directly off the stack.

**Correctness check.** A test builds 200 random graphs of 2–9 nodes, with loops, people and zero stakes, and compares every chain against an independent recursive enumeration at three thresholds. It also checks that each chain is a simple path (apart from the repeated entity closing a loop), that no chain is produced twice, and that the effective stake equals the product of the stakes.

### 3.3 Why a threshold is needed: path explosion

The minimum effective stake (`--min-stake`, default 0.01%) is needed for the traversal to finish in reasonable time, not just to tidy the output:

| Minimum effective stake | Chains (46 companies) | Longest chain |
|---|---|---|
| none | **313,822** | 14 layers |
| 0.01% (default) | 1,570 | 4 layers |

The Tata companies hold stakes in each other in loops. A chain can enter that cluster and wind through it in a different order each time, so the number of simple paths grows combinatorially. Very long winding chains carry a negligible effective stake: 14 multiplied stakes. A 0.01% cutoff removes them, and also removes the 165 holdings that round to 0.00% (Phase 1). Setting `--min-stake 0` restores everything.

### 3.4 Complexity

- **Building the graph:** O(V + E), one pass over the records. Plus sorting each adjacency list, O(E log d) where d is the largest number of owners of one company.
- **Chain enumeration:** each stack step is O(1), so the total cost is proportional to the output: the number of chains times their length. It cannot be O(V + E) in general, because the number of simple paths can grow exponentially with the number of loops; 3.3 shows it happening.
- **`reachable_owners()`:** the single-visit traversal: every entity with a direct or indirect stake in a company. It uses DFS with a visited set and an explicit stack, O(V + E). This is the bound in the plan's complexity table.

## 4. What the chains show

From `chains_report.json` (default threshold):

- **The top owner of almost every company is an unlisted holding company, not a person.**
  - Tata Sons is the top ultimate owner of 20 of the 25 Tata companies.
  - Ambadi Investments is the top ultimate owner of all 10 Murugappa companies.
  - Birla Group Holdings is the top ultimate owner of 8 of the 11 Aditya Birla companies.
  - These companies are unlisted and file no shareholding pattern, so every chain through them stops there (`no_recorded_owner`).
- **31 of 46 companies have at least one chain that reaches a natural person:** all 10 Murugappa, 10 of 11 Aditya Birla, and 11 of 25 Tata companies. Most of these are family members holding shares directly, at small stakes. Kumar Mangalam Birla holds 0.07% of Hindalco, for example. In Tata companies, the people reached are mostly public investors: Rekha Jhunjhunwala holds 4.24% of Titan.
- **Chains are shallow:** 22 companies have a longest chain of 3 layers, 4 companies of 4 layers. Depth is capped by the data. Every intermediate entity must be a *listed* company, because only listed companies have recorded owners.
- **13 chains end in a loop,** e.g. Hindalco ← Grasim ← Hindalco.

So "the largest natural-person owner" is *not* the controller. The system correctly reports that control sits in an unlisted holding company whose own owners are outside the data (Phase 1, *Known limitations*).

## 5. Known limitations

- **Chains stop at unlisted holding companies.** This is the dataset's limit, not the traversal's. Adding their owners would need MCA filings.
- **The summed ultimate-owner stake is a lower bound where loops exist** (3.1). Phase 6 computes the exact value.
- **The threshold changes what counts as a chain** (3.3). The default of 0.01% is a practical cutoff, not a legal threshold. Beneficial-ownership rules use much higher ones, such as 10%.
- **HUFs count as natural persons** (Phase 1 typing), so chains stop at them, not at their karta.
