"""Phase 2 - ingestion and parsing.

    from ownership.ingest import read_records
    result = read_records("data/ownership_relations.csv")
    result.records    # list[OwnershipRecord], in file order
    result.rejected   # malformed rows, not loaded
    result.flagged    # well-formed rows excluded for a data problem

Command line (prints a summary, writes data/ingest_report.json):

    python -m ownership.ingest [path/to/relations.csv]

Row outcomes:
  rejected  malformed: wrong field count, a required field empty, a stake that
            is not a finite number, a date that is not YYYY-MM-DD, an unknown
            entity_type, a shares_held that is not a whole number >= 0, a name
            containing control characters (e.g. NUL, a sign of a corrupted
            file), or a name with nothing left after normalising.
  flagged   parses, but cannot be a valid ownership edge:
              stake_out_of_range  stake_pct below 0 or above 100
              self_ownership      holder and held entity are identical after
                                  normalising (a self-loop in the graph)
  loaded    everything else.

Flagged rows are kept out of `records` so later phases can trust every record,
and listed in `flagged` so nothing is dropped silently.

A file-level problem (unreadable header, missing required column) raises
IngestError instead, because no row of such a file can be trusted.
"""
import csv
import io
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .normalise import normalise_name

# The five fields the plan's schema requires; the rest are Phase 1 provenance.
REQUIRED = ("holder_name", "held_name", "stake_pct", "filing_date", "entity_type")
OPTIONAL = ("holder_role", "shares_held", "held_scrip_code", "as_on_date", "group",
            "holder_cin", "held_cin")
ENTITY_TYPES = ("corporate", "individual")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class IngestError(ValueError):
    """The file as a whole cannot be parsed."""


@dataclass(frozen=True, slots=True)
class OwnershipRecord:
    """One holder's stake in one entity, as filed."""
    holder_name: str
    held_name: str
    stake_pct: float
    filing_date: date
    entity_type: str             # of the holder: "corporate" | "individual"
    holder_norm: str             # normalise_name(holder_name)
    held_norm: str               # normalise_name(held_name)
    line: int                    # 1-based line in the source file
    holder_role: str | None = None
    shares_held: int | None = None
    held_scrip_code: str | None = None
    as_on_date: date | None = None
    group: str | None = None
    holder_cin: str | None = None    # Corporate Identity Numbers, when a source carries them
    held_cin: str | None = None


@dataclass(frozen=True, slots=True)
class Issue:
    line: int
    kind: str                    # "malformed" | "stake_out_of_range" | "self_ownership"
    message: str
    row: tuple


@dataclass
class IngestResult:
    records: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    flagged: list = field(default_factory=list)

    @property
    def rows_read(self):
        return len(self.records) + len(self.rejected) + len(self.flagged)


class _RowError(Exception):
    pass


def _parse_date(value, column):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _RowError(f"{column} {value!r} is not a YYYY-MM-DD date") from None


def _parse_stake(value):
    try:
        stake = float(value)
    except ValueError:
        raise _RowError(f"stake_pct {value!r} is not a number") from None
    if not math.isfinite(stake):
        raise _RowError(f"stake_pct {value!r} is not a finite number")
    return stake


def _parse_shares(value):
    try:
        shares = int(value)
    except ValueError:
        raise _RowError(f"shares_held {value!r} is not a whole number") from None
    if shares < 0:
        raise _RowError(f"shares_held {value!r} is negative")
    return shares


def _parse_row(cells, line):
    """cells: {column: stripped value} -> OwnershipRecord. Raises _RowError."""
    for col in REQUIRED:
        if not cells[col]:
            raise _RowError(f"{col} is empty")

    etype = cells["entity_type"].lower()
    if etype not in ENTITY_TYPES:
        raise _RowError(f"entity_type {cells['entity_type']!r} is not one of {ENTITY_TYPES}")

    for col in ("holder_name", "held_name"):
        if _CONTROL.search(cells[col]):
            raise _RowError(f"{col} contains a control character")

    holder_norm = normalise_name(cells["holder_name"])
    held_norm = normalise_name(cells["held_name"])
    if not holder_norm:
        raise _RowError(f"holder_name {cells['holder_name']!r} has no letters or digits")
    if not held_norm:
        raise _RowError(f"held_name {cells['held_name']!r} has no letters or digits")

    opt = {c: cells.get(c) or None for c in OPTIONAL}
    return OwnershipRecord(
        holder_name=cells["holder_name"],
        held_name=cells["held_name"],
        stake_pct=_parse_stake(cells["stake_pct"]),
        filing_date=_parse_date(cells["filing_date"], "filing_date"),
        entity_type=etype,
        holder_norm=holder_norm,
        held_norm=held_norm,
        line=line,
        holder_role=opt["holder_role"],
        shares_held=_parse_shares(opt["shares_held"]) if opt["shares_held"] else None,
        held_scrip_code=opt["held_scrip_code"],
        as_on_date=_parse_date(opt["as_on_date"], "as_on_date") if opt["as_on_date"] else None,
        group=opt["group"],
        holder_cin=opt["holder_cin"].upper() if opt["holder_cin"] else None,
        held_cin=opt["held_cin"].upper() if opt["held_cin"] else None,
    )


def parse(stream):
    """Parse CSV text from an open text stream into an IngestResult."""
    reader = csv.reader(stream)
    try:
        header = next(reader)
    except StopIteration:
        raise IngestError("file is empty") from None
    except csv.Error as e:
        raise IngestError(f"unreadable header: {e}") from None

    header = [h.strip().lstrip("﻿") for h in header]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise IngestError(f"missing required column(s): {', '.join(missing)}")
    dupes = sorted({h for h in header if header.count(h) > 1})
    if dupes:
        raise IngestError(f"duplicate column(s): {', '.join(dupes)}")

    result = IngestResult()
    while True:
        try:
            raw = next(reader)
        except StopIteration:
            break
        except csv.Error as e:                     # e.g. NUL byte in a field
            result.rejected.append(Issue(reader.line_num, "malformed", f"unparseable row: {e}", ()))
            continue
        line = reader.line_num
        if not any(v.strip() for v in raw):        # blank line
            continue
        row = tuple(raw)
        if len(raw) != len(header):
            result.rejected.append(Issue(
                line, "malformed", f"expected {len(header)} fields, found {len(raw)}", row))
            continue

        cells = {h: v.strip() for h, v in zip(header, raw)}
        try:
            rec = _parse_row(cells, line)
        except _RowError as e:
            result.rejected.append(Issue(line, "malformed", str(e), row))
            continue

        if not 0.0 <= rec.stake_pct <= 100.0:
            result.flagged.append(Issue(
                line, "stake_out_of_range", f"stake_pct {rec.stake_pct} is outside 0-100", row))
        elif rec.holder_norm == rec.held_norm:
            result.flagged.append(Issue(
                line, "self_ownership", f"holder and held entity are both {rec.holder_norm!r}", row))
        else:
            result.records.append(rec)
    return result


def read_records(path):
    """Read and validate an ownership-relations CSV file."""
    # utf-8-sig drops a byte-order mark left by spreadsheet exports.
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return parse(fh)


def parse_text(text):
    """Convenience for tests: parse CSV given as a string."""
    return parse(io.StringIO(text, newline=""))


def summary(result):
    """Counts for the ingest report."""
    def count_by(items, key):
        out = {}
        for it in items:
            out[key(it)] = out.get(key(it), 0) + 1
        return out

    recs = result.records
    raw_names = {r.holder_name for r in recs} | {r.held_name for r in recs}
    norm_names = {r.holder_norm for r in recs} | {r.held_norm for r in recs}
    held_norms = {r.held_norm for r in recs}
    return {
        "rows_read": result.rows_read,
        "records_loaded": len(recs),
        "rows_rejected": len(result.rejected),
        "rows_flagged": count_by(result.flagged, lambda i: i.kind),
        "records_by_entity_type": count_by(recs, lambda r: r.entity_type),
        "distinct_names_raw": len(raw_names),
        "distinct_names_normalised": len(norm_names),
        "distinct_held_entities": len(held_norms),
        # Holders whose normalised name is exactly a held company's: these are
        # the corporate-to-corporate links the graph will have before Phase 3.
        "holders_matching_a_held_entity": len({r.holder_norm for r in recs} & held_norms),
        "rejected": [{"line": i.line, "reason": i.message} for i in result.rejected],
        "flagged": [{"line": i.line, "kind": i.kind, "reason": i.message} for i in result.flagged],
    }


def main(argv):
    root = Path(__file__).resolve().parent.parent
    path = Path(argv[1]) if len(argv) > 1 else root / "data" / "ownership_relations.csv"
    report = summary(read_records(path))
    text = json.dumps(report, indent=2)
    print(text)
    if len(argv) <= 1:                             # only the project dataset writes the report
        (root / "data" / "ingest_report.json").write_text(text + "\n", "utf-8")


if __name__ == "__main__":
    main(sys.argv)
