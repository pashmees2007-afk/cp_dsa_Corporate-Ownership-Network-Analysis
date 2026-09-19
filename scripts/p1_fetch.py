"""Phase 1 - data acquisition.

Downloads shareholding-pattern filings from BSE's public corporate-filings API
and caches every raw response under data/raw/ so the dataset is reproducible
and auditable.

Stages (run in order):
  python scripts/p1_fetch.py quarter    # record dates for both quarters used
  python scripts/p1_fetch.py scan       # promoter register of every active BSE equity scrip (latest quarter)
  python scripts/p1_fetch.py fallback   # previous quarter for scrips whose latest filing has no holder detail
  python scripts/p1_fetch.py public     # public (>1%) holders for companies in scope

Quarters: the latest filing (June 2026) is used. Some companies' latest filing
carries only aggregate totals with no named holders (detail not yet published);
for those, the previous quarter (March 2026) is used instead. Every cached file
is tagged by directory, so the quarter used per company is always recoverable.

Scope rule (no hand-picked company list): a company is in scope if its
promoter/promoter-group register names one of GROUP_ANCHORS.

Endpoints (discovered from BSE's own web client; unofficial, may change):
  Corp_shpPromoterNGroup_ng   ?SCRIPCODE=&QtrCode=   promoter & promoter group
  Corp_shpSec_SHPPubShold_ng  ?SCRIPCODE=&QtrCode=   public shareholders
  Corp_shpSec_shpqtrinfo_ng   ?scripcode=&qtrcode=   quarter name / dates
  ListofScripData             equity scrip master (saved as bse_scrip_list.json)
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
API = "https://api.bseindia.com/BseIndiaAPI/api/"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}
QTR_LATEST = "130.00"        # June 2026, verified via Corp_shpSec_shpqtrinfo_ng
QTR_PREVIOUS = "129.00"      # March 2026
# Group anchors: case-insensitive substring of a holder name in a promoter register.
# Chosen from the data, not from memory: they are the corporate promoters that
# appear in the most companies' registers (see docs/schema.md, "Scope").
GROUP_ANCHORS = {
    "tata sons": "Tata",
    "birla group holdings": "Aditya Birla",
    "ambadi investments": "Murugappa",
}
WORKERS = 6
DELAY = 0.15                 # seconds between requests per worker

# quarter code -> directory holding that quarter's promoter registers
PROMOTER_DIR = {QTR_LATEST: RAW / "promoter", QTR_PREVIOUS: RAW / "pro129"}
PUBLIC_DIR = {QTR_LATEST: RAW / "public", QTR_PREVIOUS: RAW / "pub129"}


def call(endpoint, scrip, qtr, retries=3):
    url = API + endpoint + "/w?" + urllib.parse.urlencode(
        {"SCRIPCODE": scrip, "QtrCode": qtr})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(1.5 * (attempt + 1))


def named_rows(payload):
    return [r for r in payload.get("Table1", []) if (r.get("Fld_ShareHolderName") or "").strip()]


def scan_one(scrip, qtr=QTR_LATEST):
    d = PROMOTER_DIR[qtr]
    d.mkdir(parents=True, exist_ok=True)
    out, status = d / f"{scrip}.json", d / f"{scrip}.status"
    if out.exists() or status.exists():
        return scrip, "cached"
    time.sleep(DELAY)
    payload = call("Corp_shpPromoterNGroup_ng", scrip, qtr)
    if payload is None:
        return scrip, "error"          # not cached -> retried on next run
    if named_rows(payload):
        out.write_text(json.dumps(payload), encoding="utf-8")
        return scrip, "named"
    status.write_text("no_named_holders")
    return scrip, "no_named_holders"


def _run(scrips, qtr):
    counts = {}
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, (_, st) in enumerate(ex.map(lambda s: scan_one(s, qtr), scrips), 1):
            counts[st] = counts.get(st, 0) + 1
            if i % 250 == 0:
                print(i, "/", len(scrips), counts, flush=True)
    print("done", counts)


def scan():
    scrips = [s["SCRIP_CD"] for s in json.loads((RAW / "bse_scrip_list.json").read_text("utf-8"))]
    _run(scrips, QTR_LATEST)


def fallback():
    """Previous quarter for scrips whose latest filing had no named holders."""
    empty = [p.stem for p in sorted(PROMOTER_DIR[QTR_LATEST].glob("*.status"))]
    print(len(empty), "scrips without holder detail in", QTR_LATEST)
    _run(empty, QTR_PREVIOUS)


def group_of(payload):
    """Group label of the first anchor named in the register, else None."""
    names = [r["Fld_ShareHolderName"].lower() for r in named_rows(payload)]
    for anchor, label in GROUP_ANCHORS.items():
        if any(anchor in n for n in names):
            return label
    return None


def in_scope():
    """[(scrip, quarter_code, promoter_json_path, group)] - latest quarter preferred."""
    found = {}
    for qtr in (QTR_PREVIOUS, QTR_LATEST):          # latest overwrites previous
        if not PROMOTER_DIR[qtr].exists():
            continue
        for f in sorted(PROMOTER_DIR[qtr].glob("*.json")):
            group = group_of(json.loads(f.read_text("utf-8")))
            if group:
                found[f.stem] = (f.stem, qtr, f, group)
    return sorted(found.values())


def public():
    scope = in_scope()
    print(len(scope), "companies in scope")

    def one(item):
        scrip, qtr, _, _ = item
        PUBLIC_DIR[qtr].mkdir(parents=True, exist_ok=True)
        out = PUBLIC_DIR[qtr] / f"{scrip}.json"
        if out.exists():
            return
        time.sleep(DELAY)
        payload = call("Corp_shpSec_SHPPubShold_ng", scrip, qtr)
        if payload is not None:
            out.write_text(json.dumps(payload), encoding="utf-8")

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(one, scope))
    print("done")


def quarter():
    """Record quarter name and start/end dates for both quarters used."""
    info = {}
    for qtr in (QTR_LATEST, QTR_PREVIOUS):
        url = API + "Corp_shpSec_shpqtrinfo_ng/w?" + urllib.parse.urlencode(
            {"scripcode": "500570", "qtrcode": qtr})
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
            row = json.loads(r.read().decode("utf-8", "ignore"))["table1"][0]
        info[qtr] = {k: row[k] for k in ("fld_quarterid", "fld_quartername", "fld_startdate", "fld_enddate")}
    (RAW / "quarter.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    {"scan": scan, "fallback": fallback, "public": public, "quarter": quarter}[sys.argv[1]]()
