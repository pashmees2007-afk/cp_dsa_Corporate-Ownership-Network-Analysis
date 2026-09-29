# Phase 2 — Ingestion and Parsing

Deliverable for Phase 2 of `CP_Implementation_Plan.docx`: an ingestion module with a unit test suite over malformed input.

| File | Contents |
|---|---|
| [`ownership/ingest.py`](../ownership/ingest.py) | File reader, record parser, validation |
| [`ownership/normalise.py`](../ownership/normalise.py) | Entity-name normaliser |
| [`tests/`](../tests) | 49 unit tests (`python -m unittest`) |
| [`data/ingest_report.json`](../data/ingest_report.json) | Result of ingesting the Phase 1 dataset |

Standard library only (Python 3.11). Parsing uses the `csv` module to split fields; the plan lists pandas for data handling, but it adds nothing to a 946-row, row-by-row validation.

## 1. Usage

```python
from ownership.ingest import read_records

result = read_records("data/ownership_relations.csv")
result.records     # list[OwnershipRecord], in file order
result.rejected    # list[Issue]: malformed rows
result.flagged     # list[Issue]: well-formed rows that cannot be edges
```

```
python -m ownership.ingest            # ingest the project dataset, write data/ingest_report.json
python -m ownership.ingest other.csv  # ingest another file, print the summary only
python -m unittest                    # run the tests
```

## 2. Record array

`records` is a Python list (the plan's "in-memory array of ownership records") of `OwnershipRecord`: an immutable dataclass with `slots`, so each record has fixed fields and no per-instance dictionary.

| Field | Type | Notes |
|---|---|---|
| `holder_name`, `held_name` | `str` | As filed, whitespace trimmed |
| `stake_pct` | `float` | 0–100 inclusive |
| `filing_date` | `date` | |
| `entity_type` | `str` | `corporate` or `individual` (holder) |
| `holder_norm`, `held_norm` | `str` | Normalised names (section 3) |
| `line` | `int` | Source line, so any record can be traced back to the file |
| `holder_role`, `shares_held`, `held_scrip_code`, `as_on_date`, `group` | optional | Phase 1 provenance columns; `None` when the column is absent or empty |

Only the plan's five schema fields are required columns. Column order does not matter and unknown columns are ignored, so files from other sources can be read if they carry those five.

## 3. Name normaliser

`normalise_name(name)` applies, in order:

| Step | Rule | Example |
|---|---|---|
| 1 | Drop `(Formerly …)` notes | `ADITYA BIRLA REAL ESTATE LIMITED (FORMERLY CENTURY TEXTILES…)` → `aditya birla real estate` |
| 2 | Case folding | `GRASIM INDUSTRIES` = `Grasim Industries` |
| 3 | `&` → `and` | `Large & Mid Cap` = `Large And Mid Cap` |
| 4 | Punctuation stripping: apostrophes deleted, everything else non-alphanumeric → space | `Children's` → `childrens`; `TRF Ltd-$` → `trf` |
| 5 | Join runs of single-letter tokens | `E.I.D.PARRY`, `E.I.D. Parry`, `EID Parry` → `eid parry`; `M A M ARUNACHALAM` = `MAM Arunachalam` |
| 6 | Remove trailing legal suffixes `ltd`, `limited`, `pvt`, `private`, `llp` (repeatedly) | `Birla Group Holdings Pvt. Limited` → `birla group holdings` |
| 7 | Remove a leading `the` | `The Tata Power Company Limited` = `Tata Power Company Ltd` |

Steps 2, 4 and 6 are the plan's (case folding, punctuation stripping, legal suffixes). Steps 1, 3, 5 and 7 were added because the dataset needs them:

- **Step 1.** A former-name note ends in its own suffix. Without this step `… LLP (Formerly … Pvt Ltd)` would lose `pvt ltd` from inside the note and keep `llp` in the middle of the name.
- **Step 5.** BSE and the filers write initials in at least three ways.
- **Step 7.** Without it, two of the most important cross-holdings (Tata Power, Indian Hotels) do not link.

Suffixes are removed only from the end of a name, so `XYZ Private Equity Fund` keeps `private`. A name made only of suffixes (e.g. `Private Limited`) is left unchanged rather than emptied.

The normaliser makes spellings canonical. It does not decide that two different strings are the same entity: `Lakshmi Venkatachalam Fly Trust` and `Lakshmi Venkatachalam Family Trust` stay different. That is Phase 3 (edit distance and the trie).

## 4. Validation

| Outcome | Condition |
|---|---|
| **Rejected** (`malformed`) | wrong number of fields; a required field empty; `stake_pct` not a finite number; a date not `YYYY-MM-DD` or not a real date; `entity_type` not `corporate`/`individual`; `shares_held` not a whole number ≥ 0; a name containing control characters (e.g. NUL); a name with no letters or digits |
| **Flagged** (`stake_out_of_range`) | `stake_pct` < 0 or > 100 |
| **Flagged** (`self_ownership`) | holder and held entity have the same normalised name |
| **File error** (`IngestError`) | empty file, missing required column, duplicate column |

The plan says to *flag* out-of-range stakes and *report* self-ownership. Both kinds of row are well formed but cannot be valid graph edges: a stake above 100% is impossible, and a self-loop would count as a trivial cycle in Phase 5. So they are kept out of `records` and listed in `flagged` with their line number and raw cells, so nothing is dropped silently. The self-ownership check compares normalised names, which catches `TATA STEEL LIMITED` holding `Tata Steel Ltd.`.

A bad row never stops ingestion. Every row is read, and each issue is reported with its line number. Blank lines are skipped, and a UTF-8 byte-order mark (left by spreadsheet exports) is removed from the header.

## 5. Test suite

49 tests in `tests/test_normalise.py` and `tests/test_ingest.py`:

- **Normaliser (19):** each legal suffix, stacked suffixes, suffix words inside a name, case, punctuation, apostrophes, `&`, initials, former-name notes (including an unclosed one), the leading article, and names that normalise to nothing. Most cases are real name variants taken from the dataset.
- **Malformed input (12):** too few or too many fields, each required field empty, non-numeric stakes (`abc`, `31.74%`, `1,5`), `nan`/`inf`, impossible dates (`2026-02-30`), bad `entity_type`, bad `shares_held`, control characters, names that normalise to nothing. Also checks that bad rows do not stop good ones and that line numbers stay correct.
- **Flagged (4):** stake above 100, negative stake, self-ownership both as an exact match and after normalising.
- **File level (4):** empty file, missing column, duplicate column, header only.
- **Well formed (9):** optional columns, column order, quoted commas, whitespace, blank lines, stake boundaries 0 and 100, byte-order mark.
- **Project dataset (1):** the Phase 1 CSV loads in full with no rejections or flags.

## 6. Result on the Phase 1 dataset

From [`data/ingest_report.json`](../data/ingest_report.json):

| | |
|---|---|
| Rows read / loaded | 946 / 946 |
| Rejected / flagged | 0 / 0 |
| Distinct names, raw → normalised | 664 → 513 (151 variants merged, 23%) |
| Held companies | 46 |
| Holder names that exactly match a held company | 23 (86 rows, all `corporate`) |

The 86 rows are the company-to-company edges that already link before entity resolution. Examples of merged variants:

| Normalised | Raw variants |
|---|---|
| `ma murugappan holdings` | 6, including three different `(Formerly …)` notes and `M.A. Murugappan Holdings LLP` |
| `grasim industries` | `GRASIM INDUSTRIES LIMITED`, `GRASIM INDUSTRIES LTD`, `Grasim Industries Limited`, `Grasim Industries Ltd` |
| `ar lakshmi achi trust` | `AR LAKSHMI ACHI TRUST`, `AR Lakshmi Achi Trust`, `AR. Lakshmi Achi Trust`, `AR.LAKSHMI ACHI TRUST` |

## 7. Left for Phase 3

- Spelling variants and typos: `Fly Trust` / `Family Trust`, `Educaton` / `Education`, truncated fund names (`… A/C AXIS MUTUAL F`).
- Parenthetical notes other than `(Formerly …)`, e.g. `(Karta - …)`, `(… hold shares on behalf of Trust)`. These change from filing to filing and are the main source of the remaining variants.
- `P` as an abbreviation of `Private` (`A M M Vellayan Sons P Ltd` → `amm vellayan sons p`). It is consistent across the variants in this dataset, so it does not split an entity, but it is not stripped.
