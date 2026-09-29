# Phase 5 — Cycle and Structure Detection

Deliverable for Phase 5 of `CP_Implementation_Plan.docx`: an anomaly report listing circular holdings, deep chains and multi-entity clusters.

| File | Contents |
|---|---|
| [`ownership/structure.py`](../ownership/structure.py) | DFS back-edge detection, Tarjan's SCC, BFS control depth, component labelling, anomaly report |
| [`data/anomaly_report.json`](../data/anomaly_report.json) | **The anomaly report** |
| [`tests/test_structure.py`](../tests/test_structure.py) | 19 tests, including cross-checks against NetworkX |

```
python -m ownership.structure          # print the summary, write data/anomaly_report.json
python -m ownership.query "grasim"     # the query now also shows control depth and circular-group membership
pip install -r requirements-dev.txt    # NetworkX, used only by the tests
python -m unittest                     # 143 tests (19 for this phase)
```

All four algorithms are hand-written and iterative (explicit stack or queue), O(V + E) time and O(V) extra space. They run on the Phase 4 graph: 405 entities and 946 holder → held edges. The whole report takes about 0.14 s.

## 1. Circular holdings

### 1.1 Algorithms

**DFS with visited and recursion-stack state** (`find_back_edges`). Each vertex is white (unvisited), grey (on the DFS stack) or black (finished). An edge into a grey vertex points back at something still on the stack, so it is a *back edge* and closes a cycle. The cycle is read directly off the stack: from the target of the back edge to the top of the stack. An edge into a black vertex is a forward or cross edge and closes nothing. The graph is acyclic exactly when no back edge exists. *Which* edges turn out to be back edges depends on the order of the DFS; *whether* any exist does not.

**Tarjan's algorithm** (`tarjan_scc`). One DFS assigns each vertex an `index` (when it was first reached) and a `low` value: the smallest index reachable from its subtree using at most one edge back into a vertex still on the component stack. When a vertex finishes with `low == index`, it is the root of a strongly connected component (SCC): everything above it on the component stack. Every SCC with two or more members is a **circular-holding group**: each member holds a stake, directly or through the others, in every other member. The DFS uses an explicit stack of (vertex, edge iterator) frames, so it has no recursion limit. A test runs it on a single cycle of 5,001 companies.

### 1.2 Result: 4 circular-holding groups, 18 companies

| # | Companies | Internal edges | Strongest internal stake | Strongest mutual holding (loop stake) |
|---|---|---|---|---|
| 1 | **11 Tata companies**: Tata Capital, Tata Chemicals, Tata Consumer Products, Tata Investment Corporation, Tata Motors, Tata Motors Passenger Vehicles, Tata Power, Tata Steel, Titan, Trent, Voltas | 39 | 5.97% | Tata Chemicals ↔ Tata Investment Corp: 0.87% × 5.97% = 0.052% |
| 2 | Carborundum Universal, Cholamandalam Financial Holdings, EID Parry (Murugappa) | 4 | < 0.01% | all internal stakes round to 0.00% |
| 3 | Grasim, Hindalco (Aditya Birla) | 2 | 4.29% | 3.92% × 4.29% = **0.168%** |
| 4 | Indian Hotels, Oriental Hotels (Tata) | 2 | 28.54% | 28.54% × 0.06% = 0.017% |

- **The Tata cluster is organised around Tata Investment Corporation.** It holds shares in all 10 other members, and 5 of them (Tata Chemicals, Tata Consumer Products, Tata Power, Tata Steel, Trent) hold shares back in it. The cluster contains 373 of the dataset's 377 simple cycles (counted with NetworkX for verification only). That is why Phase 4 found 313,822 ownership chains when no threshold was set.
- **Every loop is weak.** The strongest loop stake, the product of the stakes around a loop, is 0.17% (Grasim–Hindalco). The circular holdings are real, but they add little to effective control. Phase 6 measures their contribution exactly.
- **Group 2 exists only through holdings that round to 0.00%.** The shares exist (Phase 1 keeps every row with `shares_held > 0`), so it is a genuine cycle, but it has no economic weight. The report marks it `all_internal_stakes_below_0_01_pct`.
- The DFS found 19 back edges, all inside these four groups, as it must.

## 2. Deep chains: control depth

### 2.1 Algorithm

`bfs_levels` runs a level-order BFS with a queue, over inbound edges from a company. Level *k* holds the entities whose shortest ownership route to the company has *k* edges. Each entity is visited once, so the first level at which BFS reaches an entity is its minimum layer count.

The **controller** is the ultimate owner with the largest effective stake (Phase 4). **Control depth** is the controller's BFS level. The report gives three depths per company:

| Measure | Meaning |
|---|---|
| `control_depth` | minimum ownership layers from the company to its controller (BFS) |
| `dominant_route_layers` | layers of the controller's highest-stake route (Phase 4 chains) |
| `ownership_depth` | BFS level of the most distant owner of any kind |

### 2.2 Result

| Control depth | Companies |
|---|---|
| 1 (controller holds shares directly) | 37 |
| 2 | **9** |

The 9 **indirectly controlled** companies: the controller holds no shares of the company itself and controls it through another listed company.

| Company | Dominant route | Effective | Layers (min / route) |
|---|---|---|---|
| NACL Industries | ← Coromandel ← EID Parry ← Ambadi Investments | 11.41% | 2 / **3** |
| Automobile Corporation of Goa | ← Tata Motors ← Tata Sons | 19.76% | 2 / 2 |
| Benares Hotels | ← Indian Hotels ← Tata Sons | 18.24% | 2 / 2 |
| CG Power | ← Tube Investments ← Ambadi Investments | 20.06% | 2 / 2 |
| Nelco | ← Tata Power ← Tata Sons | 22.89% | 2 / 2 |
| Oriental Hotels | ← Indian Hotels ← Tata Sons | 11.42% | 2 / 2 |
| Rallis India | ← Tata Chemicals ← Tata Sons | 19.84% | 2 / 2 |
| TRF | ← Tata Steel ← Tata Sons | 10.99% | 2 / 2 |
| Tata Technologies | ← Tata Motors Passenger Vehicles ← Tata Sons | 22.99% | 2 / 2 |

NACL is the deepest structure in the data. Ambadi Investments reaches it through three listed layers, and the shortest route to it (2 layers) is not the one that carries the stake.

Other points from the per-company table (`control_depth` in the report):
- **Ownership depth** (the most distant owner of any kind) goes up to 5 layers. Tata Elxsi, Tata Teleservices (Maharashtra), Trent and TRF reach 5, mostly through the Tata loop.
- **Some controllers are not the group holding company.** Titan's largest ultimate owner is TIDCO (Tamil Nadu Industrial Development Corporation, a joint promoter) at 27.88%. Vodafone Idea's is the Government of India (DIPAM) at 49.00%. Tata Communications and Tejas Networks are controlled through Panatone Finvest, and Hindalco through IGH Holdings.

## 3. Multi-entity clusters: corporate families

### 3.1 Algorithm

`connected_components` labels components of the *undirected* projection: edge direction is ignored. Vertices are numbered 0..V−1, and one array `label[i]` serves as both the visited set (−1 = unvisited) and the component IDs. The traversal is DFS with an explicit stack. An optional edge filter picks which edges count.

### 3.2 Result

**Over all edges, the projection is one giant component:** 403 of the 405 entities, plus one pair. LIC, the mutual funds and foreign investors hold 1%+ in companies of all three groups, so they join the groups together. That is a fact about the market, not about control.

**Over promoter-register edges only** (holder role Promoter or Promoter Group), the groups separate:

| Family | Entities | Listed companies | Natural persons |
|---|---|---|---|
| F1 | 97 | 24 Tata | 51 |
| F2 | 86 | 10 Murugappa | 43 |
| F3 | 63 | 11 Aditya Birla | 10 |
| F4 | 2 | 1 Tata: Automotive Stampings and Assemblies, with its promoter Tata AutoComp Systems | 0 |

The other 157 entities are public shareholders only, and belong to no family.

- **The families are found by the algorithm, not assumed.** Phase 1's group labels are not used to build them; they are only shown here for comparison. The algorithm recovers the three groups exactly.
- **The one exception is informative.** Automotive Stampings is in scope because Tata Sons appears in its promoter register, but Tata Sons holds no shares there (Phase 1 drops zero-share rows). Its only promoter holding is through Tata AutoComp, an unlisted company that connects to nothing else in the data. So by holdings alone it is a separate family.

## 4. Verification

The tests compare every algorithm against NetworkX (used only in tests, as the plan specifies):

- 150 random directed graphs (1–30 nodes, three densities):
  - Tarjan's SCCs equal `nx.strongly_connected_components`;
  - "no back edges" equals `nx.is_directed_acyclic_graph`;
  - components equal `nx.connected_components`;
  - BFS levels equal `nx.single_source_shortest_path_length` on the reversed graph.
- On the real graph, the SCCs equal NetworkX's.
- On 100 random graphs, every reported cycle's edges exist, and every back edge lies inside a circular-holding group.

If NetworkX is not installed, those tests are skipped and the rest still run.

## 5. Known limitations

- **The controller is the largest ultimate owner by Phase 4's simple-chain sum**, a lower bound where loops exist. The loops here are weak (1.2), so the controller does not change, but Phase 6 computes the exact figure.
- **Families use promoter-register edges.** They reflect how companies file their promoter groups; a group that does not list a holding company as a promoter would split, as with F4.
- **Back-edge examples depend on DFS order.** They illustrate each group; the complete membership comes from Tarjan.
