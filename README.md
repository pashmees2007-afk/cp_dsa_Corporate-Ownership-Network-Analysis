# Beneficial Ownership Discovery in Corporate Networks

Course project (Data Structures and Algorithms) — Pashmee Salunkhe, Roll No. 17.
Follows `CP_Implementation_Plan.docx`.

## Status

| Phase | Status |
|---|---|
| 1. Data acquisition and schema design | **Done** |
| 2. Ingestion and parsing module | **Done** |
| 3–8 | Not started |

### Phase 1 deliverable

- Dataset: [`data/ownership_relations.csv`](data/ownership_relations.csv) — 946 ownership relations across 46 listed companies (Tata, Aditya Birla and Murugappa groups), from BSE shareholding-pattern filings.
- Schema, scope, cleaning rules and known limitations: [`docs/schema.md`](docs/schema.md).
- Build statistics: [`data/build_report.json`](data/build_report.json).

### Phase 2 deliverable

- Ingestion module: [`ownership/ingest.py`](ownership/ingest.py) (reader, parser, validation) and [`ownership/normalise.py`](ownership/normalise.py) (name normaliser).
- Unit tests: [`tests/`](tests), 49 tests, most of them over malformed input.
- Design, validation rules and results: [`docs/ingestion.md`](docs/ingestion.md). The Phase 1 dataset loads in full (946 records, 0 rejected); normalising reduces 664 distinct names to 513.

```
python -m unittest             # run the test suite
python -m ownership.ingest     # ingest the dataset, write data/ingest_report.json
```

## Reproducing

```
python scripts/p1_fetch.py quarter
python scripts/p1_fetch.py scan       # about 30-60 min, resumable
python scripts/p1_fetch.py fallback
python scripts/p1_fetch.py public
python scripts/p1_build_dataset.py    # writes data/ownership_relations.csv
```

Raw responses (`data/raw/promoter`, `pro129`, `public`, `pub129`) are git-ignored; the commands above regenerate them. Phases 1 and 2 use only the Python 3.11 standard library.
