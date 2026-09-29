# Phase 3 — Entity Resolution

Deliverable for Phase 3 of `CP_Implementation_Plan.docx`: an entity index mapping every observed name variant to a canonical entity ID, with a measured accuracy figure.

| File | Contents |
|---|---|
| [`ownership/resolve.py`](../ownership/resolve.py) | Capacity parser, match key, token check, union-find, `EntityIndex` |
| [`ownership/trie.py`](../ownership/trie.py) | Character trie: exact, prefix and near-match (Levenshtein-bounded) lookup |
| [`ownership/similarity.py`](../ownership/similarity.py) | Levenshtein distance, hand-implemented |
| [`ownership/er_eval.py`](../ownership/er_eval.py) | Pair sampling, precision/recall, ablation, blocking benchmark |
| [`data/entity_index.csv`](../data/entity_index.csv) | **The index**: 664 name variants → 405 entities |
| [`data/er_validation_pairs.csv`](../data/er_validation_pairs.csv) | 100 hand-labelled name pairs |
| [`data/er_evaluation.json`](../data/er_evaluation.json), [`data/resolution_report.json`](../data/resolution_report.json) | Measured results; every merge the fuzzy and truncation steps made |

```
python -m ownership.resolve     # build the index, write entity_index.csv + resolution_report.json
python -m ownership.er_eval     # score against the labelled pairs, write er_evaluation.json
python -m unittest              # 102 tests (53 for this phase)
```

Standard library only. The plan lists python-Levenshtein. The edit distance here is written by hand instead: it is short, and the project is about implementing the algorithms.

## 1. Result

| | |
|---|---|
| Name variants (distinct filed names, holders and held companies) | 664 |
| Entities | **405** (276 corporate, 129 individual), of which 46 are the listed companies |
| Entities with more than one variant | 134 |
| **Precision / recall on 100 labelled pairs** | **1.00 / 0.92** (24 true positives, 0 false positives, 2 false negatives) |

The biggest entities are the Murugappa family trusts. For example, `M M Muthiah Family Trust` has six variants: four filed by the trust with different trustee notes, one filed as "M M MURUGAPPAN, Trustee of M M Muthiah Family Trust", and one as "M M MURUGAPPAN (… on behalf of M M Muthiah Family Trust)".

## 2. Method

Every name goes through four steps. Then the distinct keys of each entity type are merged with a union-find (disjoint-set) structure.

### 2.1 Capacity parser: who actually holds the shares

The most common reason two names differ is not spelling. It is that the filer describes the *capacity* in which a person holds shares. In "M M MURUGAPPAN, Trustee of M M Veerappan Family Trust" the shares belong to the trust, not to M M Murugappan. Merging that row into the person would give him the trust's stake. Treating it as a separate entity would split the trust. `holding_entity()` reads these phrases and returns the entity that holds the shares:

| Rule | Pattern | Example → entity | Names |
|---|---|---|---|
| `behalf_of` | … on behalf of *Name* Trust/HUF; on behalf of the firm *Name* | "M M VENKATACHALAM (… holds on behalf of M V Muthiah Family Trust)" → M V Muthiah Family Trust | 10 |
| `partner_of` | in the capacity of Partner of *Firm* | "M.A.Alagappan (… capacity of Partner of Kadamane Estates - Firm)" → Kadamane Estates | 1 |
| `trustee_of` | X, Trustee of *Trust* | "M V SUBBIAH, trustee of Saraswathi Trust" → Saraswathi Trust | 11 |
| `karta_of` | X - As Karta of *Name* HUF | "M A M ARUNACHALAM - As Karta of M A Murugappan HUF" → M A Murugappan HUF | 11 |
| `huf` | *Name* HUF followed by anything | "M A Murugappan HUF rep. by M A M Arunachalam, Karta" → M A Murugappan HUF | 14 |
| `karta_capacity` | X (in the capacity of Karta of HUF) | → X HUF | 4 |
| `as_filed` | none of the above | the name, with annotations removed | 613 |

"On behalf of the Trust" (no name) and "on behalf of Hindalco" (not a trust, HUF or firm) do not trigger a rule. The resulting entity type follows Phase 1: an HUF is `individual` (filing category A1(a)), and a trust or firm is `corporate`.

**Annotations** are bracketed notes or " - …" tails that describe the holder rather than name it. They are removed when they contain words such as *hold, behalf, karta, trustee, capacity, through multiple schemes, various accounts, AOP, formerly*. Brackets that are part of a name stay: "Tata Teleservices (Maharashtra)" is a different company from "Tata Teleservices". A bracketed acronym of the preceding words, as in "…Protection Fund(IEPF)", is also removed.

### 2.2 Match key

The match key is the Phase 2 normalised name, plus three rules used for matching only (the index keeps the original names):

- leading honorifics removed: *Mr, Mrs, Smt, Shri, Dr*;
- trailing company-form words removed: *Company, Co, Corporation, Inc, Plc, Pte, BV, LP, LLC, A/C*. This makes "Thai Rayon Public Co." equal "Thai Rayon Public Company", and makes "Pilani Investment and Industries" equal the BSE name "…Industries Corporation Ltd";
- `Fly` → `Family`, an abbreviation used in several trust names.

Equal keys of the same entity type are one entity.

### 2.3 CIN

If a record carries a Corporate Identity Number (`holder_cin` / `held_cin`, optional columns added to the Phase 2 parser), it overrides names. Names with the same CIN are merged. Two sets with different CINs are never merged: the union-find refuses the union, so no name similarity can override it. The BSE filings used here carry no CIN (Phase 1 limitation), so on this dataset every merge is name-based. The CIN path is covered by unit tests with synthetic CINs.

### 2.4 Truncation

BSE caps names at 50 characters: "NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA MUL". A key is merged with a longer key when:
- it is a prefix of that longer key;
- the cut falls inside a word, so "Tata Teleservices" is not a truncation of "Tata Teleservices Maharashtra";
- there is exactly one such longer key. "…A/C AXIS MUTUAL F" could be "…AXIS MUTUAL FUND" or "…AXIS MUTUAL FUND A/C AXIS MIDCAP FUND", so it is left alone.

The trie's prefix query finds the longer keys. Two merges on this dataset.

### 2.5 Fuzzy matching: blocking, then a token-level check

**Blocking.** Keys are compared only with keys sharing their first 3 characters, found with a trie prefix query (the plan's "trie prefix blocking").

**Verification.** A plain Levenshtein threshold on the whole name does not work on this data. Fund names share long prefixes and differ in one word, so "quant mutual fund quant **mid** cap fund" and "…**small** cap fund" score 0.89, and "kotak … nifty **100**" and "…nifty **chem**" score 0.92. `token_match()` compares names token by token instead. Two keys match if either:
- they are equal with spaces removed ("chocka lingam" / "chockalingam"); or
- they have the same number of tokens, at most half of the tokens differ, and each differing pair
  - is longer than 3 characters (initials such as `mv`/`mm` and words like `mid`/`aif` must match exactly),
  - contains no digits (`100`/`50` must match exactly), and
  - has Levenshtein similarity ≥ 0.8.

The 13 fuzzy merges on the full dataset are listed in `resolution_report.json` and were checked by hand. All are correct: `governement`/`government`, `educaton`/`education`, `vedhika`/`vedika`, `vikram holding`/`holdings`, `childirens`/`childrens` and similar.

## 3. Evaluation

### 3.1 Validation sample

The plan asks for 100 hand-labelled name pairs. A random pair of names is almost always a non-match, so a random sample would say little about precision or recall. Pairs were instead drawn (seed 2026) from a pool of 1,736 candidate pairs. A pair is in the pool if:
- the two names differ after Phase 2 normalisation (pairs Phase 2 already merges are resolved by construction and would only inflate the score); and
- they share at least one informative token: 3+ characters, appearing in at most 10 names, so "trust", "fund" and "india" do not count.

The pool was split into four bands of token overlap (Jaccard < 0.25, 0.25–0.5, 0.5–0.75, ≥ 0.75), with 25 pairs drawn from each. The sample has 26 matches and 74 non-matches, and many of the non-matches are hard: sibling trusts with the same trustees, and funds of one fund house.

**Labelling rules.** A pair is a match (`same_entity = 1`) if both names refer to the same holder of the shares.
- A trustee or karta acting in that capacity is the trust or HUF.
- A person is never the same entity as a trust or HUF they act for.
- Differently named schemes of a fund house are different entities. A fund-wide account ("Through Multiple Schemes", "A/C" with no scheme) is different from a specific scheme.
- A name truncated so that the scheme cannot be identified does not match any specific scheme.
- Judgement calls carry a `note` in the file (e.g. Tata Motors Ltd vs Tata Motors Passenger Vehicles: two different listed companies after the 2025 demerger).

The labels were made by reading each pair, independently of the resolver's output. **They should be reviewed by the project author before submission**, since the plan calls for manual labelling.

### 3.2 Ablation

Each step added in turn (`python -m ownership.er_eval`):

| Method | Precision | Recall | F1 | Entities |
|---|---|---|---|---|
| Phase 2 normalisation only | 1.000 | 0.269 | 0.424 | 506 |
| + capacity parser | 1.000 | 0.923 | 0.960 | 420 |
| + truncation | 1.000 | 0.923 | 0.960 | 418 |
| + fuzzy, plain whole-name threshold 0.8 | 0.706 | 0.923 | 0.800 | 386 |
| + fuzzy, plain whole-name threshold 0.9 | 0.774 | 0.923 | 0.842 | 398 |
| **+ fuzzy, token-level check (full method)** | **1.000** | **0.923** | **0.960** | **405** |

- **The capacity parser does most of the work:** recall goes from 0.27 to 0.92. Most variants in this data are the same trust or HUF described by different people in different capacities, not spelling errors.
- **A plain Levenshtein threshold is harmful here.** It adds 7–10 false merges, all of them sibling fund schemes or sibling trusts. The token-level check removes all of them.
- **The two remaining errors are both false negatives:**
  - "Sigappi Arunachalam SigappiArun,MAMArunachalam&AMMeyyammaiholdsshares-Murug.Arun.ChildrenTrust" is a garbled filing with no spaces and an abbreviated trust name; no rule reads it.
  - "AXIS MUTUAL FUND TRUSTEE LIMITED A/C AXIS MUTUAL FUND" vs "AXIS MUTUAL FUND TRUSTEE LTD. A/C (Through Multiple Schemes)": two ways of writing the same fund-wide account, with no shared spelling to match on.

### 3.3 Token threshold

The sample contains few pure spelling-variant pairs, so the precision/recall figures are the same for thresholds 0.6–0.9. The threshold was therefore set from the fuzzy merges it produces on the whole dataset (`token_threshold_sweep` in `er_evaluation.json`):

| Threshold | Fuzzy merges | Compared with 0.8 |
|---|---|---|
| 0.6 | 15 | 2 wrong extra: `ma alagappan holdings = ma murugappan holdings`, `ma alagappan huf = ma murugappan huf` |
| 0.7 | 13 | same |
| **0.8** | **13** | all correct |
| 0.9 | 9 | loses 5 correct: `vikram holding(s)`, `vedhika/vedika`, `educaton`, `chldren`, `childirens` |

The true spelling variants have token similarity 0.857–0.909. The closest different-entity pairs score 0.60 (`alagappan`/`murugappan`), 0.64 (`ananyashree`/`rajashree`) and 0.71 (`deeptha`/`neetha`). 0.8 sits in the gap between them.

**This threshold, and the rules in 2.1–2.2, were developed by inspecting this same dataset.** There is no held-out data, so the figures above measure how well the rules fit these filings, not how well they would generalise to another corporate group.

### 3.4 Blocking: measured cost

The plan's complexity table gives pairwise matching as O(n² · m), "reduced by trie prefix blocking", and says the reduction should be measured. Candidate generation over the 420 distinct keys (`blocking` in `er_evaluation.json`):

| Strategy | Comparisons | Time | Verified matches |
|---|---|---|---|
| All pairs (Levenshtein with early exit) | 49,974 | 0.46 s | 15 |
| Trie near-match search, radius 20% of length (lossless) | 12.5 M DP cells | 2.30 s | 15 |
| Trie prefix blocking, 1 character | 3,534 | 0.12 s | 15 |
| Trie prefix blocking, 2 characters | 959 | 0.05 s | 15 |
| **Trie prefix blocking, 3 characters** (used) | **646** | **0.05 s** | **15** |
| Trie prefix blocking, 4 characters | 602 | 0.05 s | 14 — misses `vedhika`/`vedika` |
| Trie prefix blocking, 6 characters | 305 | 0.04 s | 13 |

- **3-character blocking** cuts comparisons 77× (49,974 → 646) and loses nothing on this data. Longer prefixes start to miss typos in the first few characters, so 3 is the longest prefix that is safe here.
- **The trie near-match search was the slowest method, which is a finding in its own right.**
  - It computes one edit-distance row per trie node, and it can only abandon a branch once every cell in the row exceeds the radius.
  - With a radius of 20% of a 60-character name (12 edits), no branch can be abandoned in the first 12 levels. The search therefore visits most of the trie.
  - Pairwise comparison with an early exit rejects most pairs immediately on length difference alone.
  - The trie search suits small fixed radii and single queries. So it is used for `EntityIndex.lookup()` (the Phase 7 search box), not for batch resolution.

Timings are single runs on the development container and will vary. The comparison counts are exact.

## 4. Data structures

| Structure | Where | Operation it supports |
|---|---|---|
| Trie (character) | `trie.py`, one per entity type | exact key lookup O(m); prefix query for blocking and truncation; bounded-Levenshtein near-match search for queries |
| Dynamic-programming table (two rows) | `similarity.py` | Levenshtein distance, O(len(a) · len(b)) time, O(min) space, early exit when every cell in a row exceeds the limit |
| Disjoint set (union-find) | `resolve.py` | merging keys into entities; path halving and union by size; each set carries its CINs so conflicting CINs cannot be joined |
| Hash maps | `EntityIndex` | name variant → entity, key → entity |

The trie depth-first walks use an explicit stack.

## 5. Using the index (for Phase 4)

```python
from ownership.ingest import read_records
from ownership.resolve import build_index

records = read_records("data/ownership_relations.csv").records
index = build_index(records)
index.entity_of(record.holder_name)     # Entity(id, name, entity_type, variants, keys, cin, listed)
index.lookup("tata sons")               # search: exact, then prefix, then near matches
```

After resolution the 946 records form 946 distinct (holder entity, held entity) pairs: no two rows collapse into the same edge. 382 distinct entities appear as holders.

## 6. Known limitations

- **No CIN in the source.** Every merge on this dataset is name-based (section 2.3).
- **Rules fitted to this data.** See 3.3: no held-out evaluation.
- **Abbreviations are not expanded beyond `Fly`.** "LIC of India" and "Life Insurance Corporation of India" stay separate. So do "Investor Education and Protection Fund" and "IEPF Authority", which are arguably the same holder.
- **Garbled names are not read.** One filing (the Sigappi Arunachalam name in 3.2) remains its own entity.
- **Single-token names are never fuzzy-matched.** The at-most-half-differ rule allows no differing token in a one-word name.
- **The labels are one person's judgement** (section 3.1). The notes in `er_validation_pairs.csv` record the calls that needed it.
