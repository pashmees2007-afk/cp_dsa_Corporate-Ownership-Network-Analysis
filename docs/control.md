# Phase 6 — Cross-holding and Control Metrics

Deliverable for Phase 6 of `CP_Implementation_Plan.docx`: control-concentration metrics per corporate family.

| File | Contents |
|---|---|
| [`ownership/matrix.py`](../ownership/matrix.py) | Dense matrix operations, walk sum I + A + A² + … by repeated multiplication |
| [`ownership/control.py`](../ownership/control.py) | Integrated (exact) stakes through cross-holdings; metrics per company and family |
| [`ownership/forest.py`](../ownership/forest.py) | Resolved chains stored as trees rooted at beneficial owners |
| [`data/control_metrics.json`](../data/control_metrics.json) | **Metrics per company and per family**, the group matrices, the tree-store benchmark |
| [`data/integrated_ownership.csv`](../data/integrated_ownership.csv) | Every (company, ultimate owner) pair: integrated stake, simple-chain stake, loop part |

```
python -m ownership.control            # print the family table, write the two data files
python -m ownership.query ultratech    # the query now also shows the controller's integrated stake
python -m unittest                     # 162 tests (19 for this phase)
```

Standard library only. The plan lists NumPy for the matrix step. The matrices are at most 11 × 11, so the operations are written by hand, and NumPy checks them in the tests (as NetworkX does in Phase 5; see `requirements-dev.txt`).

## 1. Integrated stake

Phase 4 adds up an owner's stake over **simple** chains, which never repeat an entity. Cross-holdings add routes that go round a loop: for example, Birla Group Holdings → Grasim → Hindalco → Grasim → UltraTech. Phase 4 counts none of these, so its totals are lower bounds wherever loops exist.

The **integrated stake** of U in company C is the total weight of *every* route from U to C. A route's weight is the product of the stakes along it. A route may go round loops any number of times, but it stops on reaching C. C's own holdings do not count back into C's owners; that part is reported separately as C's self-ownership (section 3).

With x_v = integrated stake of v in C:

```
x_C = 1
x_v = Σ over v's holdings (v → w, stake s) of s · x_w          (v ≠ C)
```

### 1.1 Computation

1. **Outside the circular groups the graph is acyclic.** Each x_v follows from the x of the companies v holds. Tarjan's algorithm (Phase 5) outputs components in exactly that order (a component is finished only after everything it can reach), so one pass over its output computes every x. This is O(V + E) per company.
2. **Inside a circular group S** the values depend on each other: x_S = A_S · x_S + b. Here A_S is the group's **stake matrix** (A[i][j] = stake of member i in member j), and b holds the members' stakes outside the group, already computed. So

   ```
   x_S = (I + A_S + A_S² + A_S³ + …) · b
   ```

   Entry (i, j) of A_S^k is the weight of all k-step routes from i to j, so each power adds the routes that go round the loops once more. The series is computed by **repeated matrix multiplication** until a term falls below 10⁻¹⁵ in every entry. This is O(k³) per term for a group of k companies, and it converges because no company in these loops is anywhere near 100% held inside the loop. The series matrix of each group is computed once and reused for every company. The exception is the group containing C itself, where C's row is zeroed (routes stop at C).

The whole computation, for all 46 companies, runs in about 0.6 s including the report.

### 1.2 The group matrices

Stake matrices (percent; row = holder, column = held) and their series (I − A)⁻¹:

| Group | A (stakes, %) | I + A + A² + … | Terms |
|---|---|---|---|
| Grasim, Hindalco | `[[0, 3.92], [4.29, 0]]` | `[[1.0017, 0.0393], [0.0430, 1.0017]]` | 11 |
| Indian Hotels, Oriental Hotels | `[[0, 28.54], [0.06, 0]]` | `[[1.0002, 0.2854], [0.0006, 1.0002]]` | 8 |
| Tata cluster (11 companies) | 39 non-zero entries, largest 5.97% | see `control_metrics.json` | 10 |
| Carborundum, Cholamandalam Fin., EID Parry | all 0.00% as filed | I | 1 |

The diagonal of the series shows how much each company's own value goes round its loop and returns: 1.0017 for Grasim means 0.17% comes back through Hindalco.

## 2. Result: loops change almost nothing

| Measure | Result |
|---|---|
| Largest loop contribution to any company's traced ownership | **+0.055 percentage points** (UltraTech Cement, via Grasim ↔ Hindalco) |
| Next largest | Aditya Birla Capital +0.053, Rallis India +0.016, Aditya Birla Lifestyle Brands and Aditya Birla Fashion & Retail +0.011 each |
| Largest gap between a controller's integrated stake and its simple-chain stake | 0.024 pp (UltraTech: 14.790% vs 14.766%) |
| Companies whose controller changes | **none** |

- **Phase 4 was already close.** Its simple-chain totals are within 0.06 percentage points of the exact values everywhere, and every controller identified in Phases 4–5 stands.
- **Loops don't hide control here.** The loops in this data are too weak: the strongest loop multiplies to 0.17%. They are a structural anomaly (Phase 5), not a way of concealing control.
- **The routine matters in general, not just here.** A test uses a hand-solved example where the loop changes the owner's stake from 0.315 to 0.335, and random graphs where it matters more.

## 3. Self-ownership

A company in a circular group indirectly owns part of itself: the weight of routes that leave it and come back.

| Company | Indirect stake in itself |
|---|---|
| Grasim, Hindalco | 0.168% each (3.92% × 4.29%) |
| Tata Investment Corporation | 0.073% |
| Tata Chemicals | 0.052% |
| Indian Hotels, Oriental Hotels | 0.017% each |
| Tata Consumer Products, Tata Power, Trent, Tata Steel | 0.014%, 0.003%, 0.003%, 0.002% |

## 4. Control-concentration metrics

Per company (`companies` in `control_metrics.json`):

| Metric | Meaning |
|---|---|
| `traced_pct` | share of the company traced to ultimate owners: the sum of their integrated stakes. The rest is public holdings below 1%, which the filings do not name |
| `controller`, `controller_pct` | ultimate owner with the largest integrated stake |
| `top3_pct` | integrated stakes of the three largest ultimate owners |
| `hhi` | Herfindahl–Hirschman index of the ultimate owners' integrated stakes, in percentage points (0–10,000) |
| `family_pct` | integrated stake of the ultimate owners in the company's own family (Phase 5 promoter family) |
| `self_ownership_pct`, `loop_contribution_pct` | sections 3 and 2 |

Per family (`families`), over its listed companies:

| Family | Companies | Family stake: mean / median | min – max | > 50% | 25–50% | < 25% | Controller stake, mean | HHI, mean |
|---|---|---|---|---|---|---|---|---|
| F1 Tata | 24 | **42.5% / 39.8%** | 11.1 – 84.7% | 7 | 12 | 5 | 37.2% | 1,808 |
| F2 Murugappa | 10 | 34.4% / 35.0% | 12.7 – 55.6% | 1 | 6 | 3 | 28.2% | 964 |
| F3 Aditya Birla | 11 | 35.5% / 35.4% | 21.0 – 58.7% | 2 | 6 | 3 | 23.9% | 896 |
| F4 Automotive Stampings | 1 | 75.0% | — | 1 | 0 | 0 | 75.0% | 5,625 |

The 25% and 50% thresholds mark control levels under Indian company law. Above 50%, a family controls ordinary resolutions. Above 25%, it can block special resolutions, which need 75% of votes.

- **Tata is the most concentrated group.** It has the highest family stake (mean 42.5%, 7 companies above 50%) and the highest HHI (1,808). The concentration sits almost entirely in one vehicle: Tata Sons is the controller of 20 of 24 companies. The others are Panatone Finvest (Tata Communications, Tejas Networks), Tata Teleservices Ltd, and TIDCO for Titan. TIDCO is a Tamil Nadu state company, but it is a co-promoter of Titan, so it counts as part of the family.
- **Murugappa has one vehicle with lower stakes.** Ambadi Investments controls all 10 companies, with a mean controller stake of 28.2%. The family stake adds individual members and trusts on top of that; Phase 3's entity resolution is what makes those trusts countable.
- **Aditya Birla's control is spread across more vehicles:**
  - Birla Group Holdings is the controller of 8 of 11 companies, with the lowest mean controller stake (23.9%).
  - IGH Holdings (Hindalco) and Jayashree Finvest (Jay Shree Tea) control one company each, and the Government of India controls Vodafone Idea (49%, against the Birla family's 23.2%).
- **The least-held companies are the indirectly controlled ones from Phase 5:** TRF (family 11.1%), NACL (12.7%), Rallis (20.0%) and Automobile Corporation of Goa (20.8%). Control there runs through a listed intermediate, so the family's integrated stake is the product of two stakes.
- **About 57% of a company is traced on average.** The family stakes above are shares of the whole company, not of the traced part.

## 5. Chains stored as trees

The plan asks for resolved chains to be stored "as a tree rooted at the beneficial owner to support fast repeated queries without re-traversal". `OwnershipForest` stores every Phase 4 chain that ends at a beneficial owner, reversed:
- the owner is the root;
- each child is a company its parent holds shares in;
- each root-to-node path is one resolved chain.

Chains from the same owner share their common prefix: Tata Sons → Tata Investment Corporation is stored once, however many chains continue below it. Each node keeps a parent pointer, and an index maps each entity to its tree nodes.

| | |
|---|---|
| Trees (beneficial owners) | 335 |
| Chains stored | 1,529 (the 41 circular or below-threshold chains have no owner at the root and are not stored) |
| Tree nodes | 1,864, against 4,043 entity entries if every chain were stored separately (54% fewer) |

**Queries without re-traversal.**
- `chains_of(company)` finds the company's nodes in the index and follows parent pointers to the root.
- `portfolio(owner)` walks one owner's tree.

Measured on all companies and owners, 20 repetitions each (timings vary from run to run; see `tree_store` in the report):

| Query | Graph traversal (Phase 4) | Tree | Ratio |
|---|---|---|---|
| Chains of every listed company | ~2.2 ms | ~1.2 ms | ~1.8× |
| Everything one owner reaches | ~2–3 ms (every company's chains must be enumerated) | ~0.002 ms (mean per owner) | ~1,000× or more |

- **Company-side queries gain little.** Chains are at most 4 layers deep and the DFS is already cheap.
- **Owner-side queries are where the tree pays off.** Phase 4 can only enumerate chains company by company, so "what does Tata Sons reach, and through which companies?" requires the whole traversal; the tree answers it by walking one tree. The owner-side mean is over all 335 owners, most of which have small trees.
- **Correctness:** a test checks that the forest returns exactly Phase 4's chains, same order and same stakes, for all 46 companies.

The plan also mentions a linked list for director interlocks. The filings contain no director data, so that part is not built.

## 6. Verification

- **Walk sum vs matrix inverse:** I + A + A² + … equals NumPy's `inv(I − A)` on 50 random matrices of up to 12 × 12.
- **Integrated stakes vs linear solve:** they equal `numpy.linalg.solve` of (I − A′)x = e_C on 100 random graphs with loops, where A′ is the graph's full stake matrix with C's row zeroed.
- **Acyclic graphs:** on 100 random acyclic graphs, integrated stakes equal Phase 4's simple-chain sums exactly, since there are no loops to add.
- **Graphs with loops:** integrated stakes are never below the simple-chain sums, and never total more than 100%.
- **Hand-solved cases:** a hand-solved loop, a mutual holding with the target, and non-convergence for a loop that holds 100%.

## 7. Known limitations

- **Integrated stake measures economic interest, not voting control.** It multiplies stakes along routes. Voting control through a chain is often modelled differently: e.g. a majority stake at each layer passes on full control. The 25% and 50% thresholds in section 4 are applied to the economic figure.
- **Traced ownership is partial.** Shares held by public investors below 1% are not named in the filings, and unlisted holding companies have no recorded owners. Family stakes cover only what the data traces.
- **Families come from promoter-register edges (Phase 5),** so co-promoters such as TIDCO count as family.
- **Timings are single-machine measurements** and vary between runs; the node and chain counts are exact.
