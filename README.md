# Beneficial Ownership Discovery in Corporate Networks

Course project (Data Structures and Algorithms) — Pashmee Salunkhe, Roll No. 17.
Follows `CP_Implementation_Plan.docx`.

## Status

| Phase | Status |
|---|---|
| 1. Data acquisition and schema design | **Done** |
| 2–8 | Not started |

### Phase 1 deliverable

- Dataset: [`data/ownership_relations.csv`](data/ownership_relations.csv) — 946 ownership relations across 46 listed companies (Tata, Aditya Birla and Murugappa groups), from BSE shareholding-pattern filings.
- Schema, scope, cleaning rules and known limitations: [`docs/schema.md`](docs/schema.md).
- Build statistics: [`data/build_report.json`](data/build_report.json).

## Reproducing

```
python scripts/p1_fetch.py quarter
python scripts/p1_fetch.py scan       # about 30-60 min, resumable
python scripts/p1_fetch.py fallback
python scripts/p1_fetch.py public
python scripts/p1_build_dataset.py    # writes data/ownership_relations.csv
```

Raw responses (`data/raw/promoter`, `pro129`, `public`, `pub129`) are git-ignored; the commands above regenerate them. The Phase 1 scripts use only the Python 3.11 standard library.
