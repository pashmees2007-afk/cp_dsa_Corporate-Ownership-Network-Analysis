# Phase 1 — Data Sources and Schema

Deliverable for Phase 1 of `CP_Implementation_Plan.docx`: a cleaned CSV dataset plus a documented schema.

Dataset: [`data/ownership_relations.csv`](../data/ownership_relations.csv) — **946 ownership relations**, 46 listed companies, 620 distinct holder names. Build statistics are in [`data/build_report.json`](../data/build_report.json).

## 1. Data source

| Item | Value |
|---|---|
| Source | BSE shareholding-pattern filings (SEBI LODR format), read through BSE's public corporate-filings API |
| Registers used | Promoter and Promoter Group register; Public shareholder register |
| Quarter | June 2026 (as on 30 Jun 2026) for 45 companies; March 2026 (as on 31 Mar 2026) for 1 company |
| Retrieved | September 2026 |

Endpoints (unofficial; found from BSE's own web client, so they may change without notice):

| Endpoint | Use |
|---|---|
| `Corp_shpPromoterNGroup_ng` | Promoter and promoter-group register for a scrip and quarter |
| `Corp_shpSec_SHPPubShold_ng` | Public shareholder register |
| `Corp_shpSec_shpqtrinfo_ng` | Quarter name and start/end dates |
| `ListofScripData` | Master list of active BSE equity scrips (5,037) |

The plan also names MCA and NSE. Neither was used: NSE's site blocked programmatic access (HTTP 403) and MCA bulk data was not attempted. BSE was sufficient and is freely accessible, which is the fallback the plan's risk table names.

## 2. Scope

The plan says to begin with a bounded set rather than a national dataset. Scope is **three corporate groups**, identified from the data rather than from a hand-picked company list:

1. Every active BSE equity scrip (5,037) was scanned for its promoter register.
2. A company is in scope if its register names one of these anchors (case-insensitive substring of a holder name):

| Anchor | Group label | Companies |
|---|---|---|
| `tata sons` | Tata | 25 |
| `birla group holdings` | Aditya Birla | 11 |
| `ambadi investments` | Murugappa | 10 |

The anchors were chosen because they are the corporate promoters that appear in the most companies' registers, after the Government of India ("President of India", 58 companies). The Government was excluded because state holdings of public-sector companies do not form layered corporate chains. Tata alone yielded 279 relations after cleaning (about 390 before the public-register cleaning step), below the plan's 500 minimum, so two more groups were added. The Aditya Birla and Murugappa registers also name family members, so chains there can end at natural persons.

The `group` column records which anchor matched. The label is a convenience for filtering; it is not filed data.

## 3. Schema

One row = one holder's stake in one listed company, as reported in one filing.

The plan specifies five fields (holder entity, held entity, stake percentage, filing date, entity type). These are columns 1–5. Columns 6–10 are additions for provenance and to keep information the rounded percentage loses.

| # | Column | Type | Meaning |
|---|---|---|---|
| 1 | `holder_name` | string | Holder exactly as filed (whitespace collapsed only). Not normalised — variants are kept for Phase 3 entity resolution |
| 2 | `held_name` | string | Listed company whose register the row comes from (BSE long name) |
| 3 | `stake_pct` | float | Holder's shareholding as % of the company's total shares, as filed. Rounded to 2 decimals in the source |
| 4 | `filing_date` | date | Date part of BSE field `Fld_AuthoriseDate` for the filing |
| 5 | `entity_type` | `corporate` \| `individual` | Type of the **holder**. Held entities are always listed companies |
| 6 | `holder_role` | `Promoter` \| `Promoter Group` \| `Public (>1%)` | Which register and category the holder appears in |
| 7 | `shares_held` | int | Number of shares held, as filed |
| 8 | `held_scrip_code` | string | BSE scrip code of the held company |
| 9 | `as_on_date` | date | Quarter-end date of the register used |
| 10 | `group` | string | Group anchor that put the company in scope |

### `entity_type` rule

- Promoter register: `individual` if the filing category is A1(a) or A2(a) (Individuals/HUF; NRI/foreign individuals). Everything else is `corporate`.
- Public register: `individual` if the category is Resident Individuals, NRIs, Foreign Nationals, Directors' relatives or Key Managerial Personnel. Everything else is `corporate`.
- `corporate` means "not a natural person": companies, trusts, mutual-fund schemes, insurers, foreign investors, governments.
- The filing category cannot separate natural persons from Hindu Undivided Families in category A1(a). All 30 HUF-named holders are typed `individual`. Four holders filed as a trustee acting for a trust are also typed `individual`. Neither has a further ownership filing, so both terminate a chain.

## 4. Cleaning rules

Names are deliberately not normalised here: suffix stripping is Phase 2 and variant matching is Phase 3.

1. Keep only rows with a named holder. Sub-total rows have none.
2. Keep only rows with `shares_held > 0`. Promoter-group registers list many members with zero shares, and the public registers have some too (7,886 such named rows were dropped across both); zero-share promoter-group rows record group membership, not a stake.
3. Public register: drop the "Any Other" buckets (196 rows). Their names are category labels such as "Trusts", "Clearing Members", "FII" and "HUF", not holders. Kept, they would become false graph nodes.
4. Drop exact duplicates on (holder, held, role): 1 row.

Validation results on the delivered file: no missing values; `stake_pct` between 0.0 and 78.8; no stake above 100; no holder identical to its held company; summed stakes per company never exceed 100.

## 5. Dataset summary

| | Tata | Aditya Birla | Murugappa | Total |
|---|---|---|---|---|
| Companies | 25 | 11 | 10 | 46 |
| Relations | 279 | 236 | 431 | 946 |
| Holder is `corporate` | 209 | 184 | 225 | 618 |
| Holder is `individual` | 70 | 52 | 206 | 328 |

By role: Promoter 189, Promoter Group 525, Public (>1%) 232. All public rows are at least 1.0%.

### Preliminary structure

A rough name match (lower-casing and dropping "Limited/Ltd/Private/Pvt") links 88 corporate holders to another company in the dataset (Tata 58, Aditya Birla 19, Murugappa 11). It also shows circular holdings: Grasim–Hindalco; Oriental Hotels–Indian Hotels; Cholamandalam Financial Holdings–Carborundum Universal; and a ten-company Tata cluster. This is a quick check on the data, not a result. Phase 3 replaces the rough match with proper entity resolution.

## 6. Known limitations

- **No Corporate Identity Number.** The filings carry no CIN, so the plan's "CIN first, string matching as fallback" cannot use CIN. Phase 3 must rely on string matching alone unless CINs are added from another source.
- **Unlisted holders are dead ends.** An unlisted holder such as Tata Sons Private Limited has no shareholding filing, so it has no incoming edges. Its owners are not in this dataset and were not added from outside knowledge.
- **Mixed quarters.** One company (Tata Investment Corporation, 8 rows) is from March 2026 because its June 2026 filing had aggregate totals only. Every row carries `as_on_date`.
- **0.00% stakes.** 165 rows have `shares_held > 0` but round to `stake_pct` 0.0. They are kept because they are real holdings; `shares_held` preserves the magnitude. Phase 4 may choose to apply a threshold.
- **Public register is partial.** Only holders of at least 1% are named, so public ownership below that is absent.
- **Promoter register as filed.** Promoter and promoter-group holders are taken as the company filed them. Completeness against other sources was not checked.
- **Unofficial API.** Re-running the fetch later may return different quarters or a changed format.
- **Not verified against MCA.** Holder and company names are as BSE filed them.

## 7. Reproducing

```
python scripts/p1_fetch.py quarter
python scripts/p1_fetch.py scan       # about 30-60 min, resumable
python scripts/p1_fetch.py fallback   # previous quarter where the latest has no holder detail
python scripts/p1_fetch.py public
python scripts/p1_build_dataset.py
```

Raw responses are cached under `data/raw/` (git-ignored; about 135 MB). The scrip list and quarter dates are committed.
