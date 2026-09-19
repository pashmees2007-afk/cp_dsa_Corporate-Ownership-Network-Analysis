"""Phase 1 - build the cleaned ownership-relations CSV from the cached raw filings.

    python scripts/p1_build_dataset.py

Reads  data/raw/promoter/*.json (+ data/raw/public/*.json for in-scope companies)
Writes data/ownership_relations.csv and data/build_report.json

Cleaning rules (deliberately minimal - name normalisation is Phase 2, entity
resolution is Phase 3, so holder/held names are kept exactly as filed apart
from whitespace collapsing):
  1. Keep only named holder rows (aggregate/sub-total rows have no holder name).
  2. Keep only rows with shares_held > 0 (zero-share promoter-group members are
     group membership, not an ownership stake).
  3. Collapse runs of whitespace in names; strip ends.
  4. Drop exact duplicate (holder, held, role) rows.
"""
import csv
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
GROUP_ANCHOR = "tata sons"

FIELDS = ["holder_name", "held_name", "stake_pct", "filing_date", "entity_type",
          "holder_role", "shares_held", "held_scrip_code", "as_on_date"]

# Promoter-register filing categories (SEBI shareholding-pattern format).
INDIVIDUAL_PROMOTER_CODES = {"A1a", "A2a"}
# Public-register category text that denotes natural persons.
INDIVIDUAL_PUBLIC_LEVEL = re.compile(
    r"Resident Individuals|Non Resident Indians|Foreign Nationals|"
    r"Directors and their relatives|Key Managerial", re.I)


def clean(name):
    return re.sub(r"\s+", " ", name).strip()


def rows_of(payload):
    return [r for r in payload.get("Table1", []) if clean(r.get("Fld_ShareHolderName") or "")]


def filing_date(payload):
    raw = payload["Table"][0]["Fld_AuthoriseDate"]        # e.g. 2026-07-21T19:29:57.253
    return datetime.fromisoformat(raw).date().isoformat()


def build():
    quarter = json.loads((RAW / "quarter.json").read_text("utf-8"))
    as_on = datetime.strptime(quarter["fld_enddate"], "%d %b %Y").date().isoformat()

    out, seen = [], set()
    report = {"quarter": quarter["fld_quartername"], "as_on_date": as_on,
              "companies_in_scope": 0, "skipped_zero_share_rows": 0,
              "skipped_duplicates": 0, "rows_by_role": {}, "public_files_missing": []}

    def add(holder, held, pct, fdate, etype, role, shares, scrip):
        key = (holder.lower(), held.lower(), role)
        if key in seen:
            report["skipped_duplicates"] += 1
            return
        seen.add(key)
        out.append({"holder_name": holder, "held_name": held, "stake_pct": pct,
                    "filing_date": fdate, "entity_type": etype, "holder_role": role,
                    "shares_held": shares, "held_scrip_code": scrip, "as_on_date": as_on})
        report["rows_by_role"][role] = report["rows_by_role"].get(role, 0) + 1

    for f in sorted((RAW / "promoter").glob("*.json")):
        payload = json.loads(f.read_text("utf-8"))
        if not any(GROUP_ANCHOR in clean(r["Fld_ShareHolderName"]).lower() for r in rows_of(payload)):
            continue
        scrip = f.stem
        held = clean(payload["Table2"][0]["sLongName"])
        fdate = filing_date(payload)
        report["companies_in_scope"] += 1

        for r in rows_of(payload):
            shares = r["Fld_TotalNoOfShares"]
            if not shares or shares <= 0:
                report["skipped_zero_share_rows"] += 1
                continue
            etype = "individual" if r["Fld_Code"] in INDIVIDUAL_PROMOTER_CODES else "corporate"
            add(clean(r["Fld_ShareHolderName"]), held, r["Fld_TotalPercentageOf_A_B_C2"],
                fdate, etype, (r.get("FLd_ShareholderType") or "Promoter Group").strip(),
                shares, scrip)

        pub = RAW / "public" / f"{scrip}.json"
        if not pub.exists():
            report["public_files_missing"].append(scrip)
            continue
        ppayload = json.loads(pub.read_text("utf-8"))
        for r in rows_of(ppayload):
            shares = r["Fld_TotalNoOfShares"]
            if not shares or shares <= 0:
                report["skipped_zero_share_rows"] += 1
                continue
            level = r.get("Fld_Level") or ""
            etype = "individual" if INDIVIDUAL_PUBLIC_LEVEL.search(
                (r.get("Fld_SubCategory") or "") + " " + level) else "corporate"
            add(clean(r["Fld_ShareHolderName"]), held, r["Fld_TotalPercentageOf_A_B_C2"],
                filing_date(ppayload), etype, "Public (>1%)", shares, scrip)

    out.sort(key=lambda r: (r["held_name"], -r["stake_pct"], r["holder_name"]))
    with open(ROOT / "data" / "ownership_relations.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    report["total_relations"] = len(out)
    (ROOT / "data" / "build_report.json").write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    build()
