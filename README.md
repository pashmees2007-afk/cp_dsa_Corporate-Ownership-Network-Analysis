# Beneficial Ownership Discovery in Corporate Networks

Course project (Data Structures and Algorithms) — Pashmee Salunkhe, Roll No. 17.
Follows `CP_Implementation_Plan.docx`.

## Status

| Phase | Status |
|---|---|
| 1. Data acquisition and schema design | **Done** |
| 2. Ingestion and parsing module | **Done** |
| 3. Entity resolution | **Done** |
| 4. Graph construction and chain traversal | **Done** — first end-to-end build |
| 5–8 | Not started |

### Phase 1 deliverable

- Dataset: [`data/ownership_relations.csv`](data/ownership_relations.csv) — 946 ownership relations across 46 listed companies (Tata, Aditya Birla and Murugappa groups), from BSE shareholding-pattern filings.
- Schema, scope, cleaning rules and known limitations: [`docs/schema.md`](docs/schema.md).
- Build statistics: [`data/build_report.json`](data/build_report.json).

### Phase 2 deliverable

- Ingestion module: [`ownership/ingest.py`](ownership/ingest.py) (reader, parser, validation) and [`ownership/normalise.py`](ownership/normalise.py) (name normaliser).
- Unit tests: [`tests/`](tests), 49 tests for Phase 2, most of them over malformed input.
- Design, validation rules and results: [`docs/ingestion.md`](docs/ingestion.md). The Phase 1 dataset loads in full (946 records, 0 rejected); normalising reduces 664 distinct names to 513.

```
python -m unittest             # run the test suite
python -m ownership.ingest     # ingest the dataset, write data/ingest_report.json
```

### Phase 3 deliverable

- Entity index: [`data/entity_index.csv`](data/entity_index.csv) maps all 664 name variants to 405 canonical entity IDs.
- Resolver: [`ownership/resolve.py`](ownership/resolve.py) (capacity parser, match key, union-find), [`ownership/trie.py`](ownership/trie.py) (trie with prefix and near-match lookup), [`ownership/similarity.py`](ownership/similarity.py) (Levenshtein).
- Accuracy: **precision 1.00, recall 0.92** on 100 hand-labelled name pairs ([`data/er_validation_pairs.csv`](data/er_validation_pairs.csv)), with an ablation and a blocking benchmark in [`data/er_evaluation.json`](data/er_evaluation.json).
- Method, evaluation and limitations: [`docs/entity_resolution.md`](docs/entity_resolution.md).

```
python -m ownership.resolve    # build the entity index
python -m ownership.er_eval    # precision / recall, ablation, blocking benchmark
```

### Phase 4 deliverable

- Query interface: `python -m ownership.query "<company name>"` prints the company's ownership chains ranked by effective stake, its ultimate owners, and any circular holdings on its chains.
- Graph: [`ownership/graph.py`](ownership/graph.py) (adjacency lists). Traversal: [`ownership/chains.py`](ownership/chains.py) (DFS with an explicit stack).
- All chains of all 46 listed companies: [`data/ownership_chains.csv`](data/ownership_chains.csv) (1,570 at the default 0.01% threshold; 313,822 with none), summary in [`data/chains_report.json`](data/chains_report.json).
- Method and findings: [`docs/chains.md`](docs/chains.md).

```
python -m ownership.query "tata steel"
python -m ownership.query --report     # regenerate the chain files
```

## Reproducing

```
python scripts/p1_fetch.py quarter
python scripts/p1_fetch.py scan       # about 30-60 min, resumable
python scripts/p1_fetch.py fallback
python scripts/p1_fetch.py public
python scripts/p1_build_dataset.py    # writes data/ownership_relations.csv
```

Raw responses (`data/raw/promoter`, `pro129`, `public`, `pub129`) are git-ignored; the commands above regenerate them. Phases 1–4 use only the Python 3.11 standard library.
