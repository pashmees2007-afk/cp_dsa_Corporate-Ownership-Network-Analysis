# Beneficial Ownership Discovery in Corporate Networks

Course project (Data Structures and Algorithms) — Pashmee Salunkhe, Roll No. 17.
Follows `CP_Implementation_Plan.docx`.

## Status

**Phase 1 — Data acquisition and schema design: in progress.**

Done so far:
- Data source identified: BSE shareholding-pattern filings (promoter & promoter group, public >1% holders), via BSE's public corporate-filings API. Quarter used: June 2026 (as on 30 Jun 2026).
- Scope: Tata group. A company is in scope if its filed promoter register names "Tata Sons". Membership is derived from the filings, not hand-picked.
- `scripts/p1_fetch.py` — scans every active BSE equity scrip and caches raw responses.
- `scripts/p1_build_dataset.py` — builds `data/ownership_relations.csv` from the cache.

Not yet done: the full scan has not completed, so the CSV dataset and `docs/schema.md` are not in this commit.

## Reproducing

```
python scripts/p1_fetch.py quarter
python scripts/p1_fetch.py scan      # ~35 min, resumable; caches to data/raw/promoter/
python scripts/p1_fetch.py public    # public holders for in-scope companies
python scripts/p1_build_dataset.py   # writes data/ownership_relations.csv
```

Raw responses (`data/raw/promoter`, `data/raw/public`) are git-ignored; regenerate them with the commands above.

## Data source note

The BSE endpoints are unofficial (found from BSE's own web client) and may change. Filings carry no Corporate Identity Number, so Phase 3 entity resolution will rely on string matching.
