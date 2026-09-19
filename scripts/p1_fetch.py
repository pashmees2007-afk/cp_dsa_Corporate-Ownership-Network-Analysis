"""Phase 1 - data acquisition.

Downloads shareholding-pattern filings from BSE's public corporate-filings API
and caches every raw response under data/raw/ so the dataset is reproducible
and auditable.

Stages (run in order):
  python scripts/p1_fetch.py scan     # promoter register of every active BSE equity scrip
  python scripts/p1_fetch.py public   # public (>1%) holders for companies in scope

Scope rule (no hand-picked company list): a company is in scope if its
promoter/promoter-group register names GROUP_ANCHOR.

Endpoints (discovered from BSE's own web client; unofficial, may change):
  Corp_shpPromoterNGroup_ng   ?SCRIPCODE=&QtrCode=   promoter & promoter group
  Corp_shpSec_SHPPubShold_ng  ?SCRIPCODE=&QtrCode=   public shareholders
  ListofScripData             equity scrip master (already saved)
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
QTR_CODE = "130.00"          # June 2026, verified via Corp_shpSec_shpqtrinfo_ng
GROUP_ANCHOR = "tata sons"   # case-insensitive substring of a holder name
WORKERS = 4
DELAY = 0.15                 # seconds between requests per worker


def call(endpoint, scrip, retries=3):
    url = API + endpoint + "/w?" + urllib.parse.urlencode(
        {"SCRIPCODE": scrip, "QtrCode": QTR_CODE})
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


def scan_one(scrip):
    out = RAW / "promoter" / f"{scrip}.json"
    status = RAW / "promoter" / f"{scrip}.status"
    if out.exists() or status.exists():
        return scrip, "cached"
    time.sleep(DELAY)
    payload = call("Corp_shpPromoterNGroup_ng", scrip)
    if payload is None:
        return scrip, "error"          # not cached -> retried on next run
    if named_rows(payload):
        out.write_text(json.dumps(payload), encoding="utf-8")
        return scrip, "named"
    status.write_text("no_named_holders")
    return scrip, "no_named_holders"


def scan():
    scrips = [s["SCRIP_CD"] for s in json.loads((RAW / "bse_scrip_list.json").read_text("utf-8"))]
    counts = {}
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, (_, st) in enumerate(ex.map(scan_one, scrips), 1):
            counts[st] = counts.get(st, 0) + 1
            if i % 250 == 0:
                print(i, "/", len(scrips), counts, flush=True)
    print("done", counts)


def in_scope_scrips():
    scope = []
    for f in sorted((RAW / "promoter").glob("*.json")):
        payload = json.loads(f.read_text("utf-8"))
        if any(GROUP_ANCHOR in r["Fld_ShareHolderName"].lower() for r in named_rows(payload)):
            scope.append(f.stem)
    return scope


def public():
    scope = in_scope_scrips()
    print(len(scope), "companies in scope")

    def one(scrip):
        out = RAW / "public" / f"{scrip}.json"
        if out.exists():
            return
        time.sleep(DELAY)
        payload = call("Corp_shpSec_SHPPubShold_ng", scrip)
        if payload is not None:
            out.write_text(json.dumps(payload), encoding="utf-8")

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(one, scope))
    print("done")


def quarter():
    """Record quarter name and start/end dates for QTR_CODE (Corp_shpSec_shpqtrinfo_ng)."""
    url = API + "Corp_shpSec_shpqtrinfo_ng/w?" + urllib.parse.urlencode(
        {"scripcode": "500570", "qtrcode": QTR_CODE})
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
        row = json.loads(r.read().decode("utf-8", "ignore"))["table1"][0]
    info = {k: row[k] for k in ("fld_quarterid", "fld_quartername", "fld_startdate", "fld_enddate")}
    (RAW / "quarter.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(info)


if __name__ == "__main__":
    {"scan": scan, "public": public, "quarter": quarter}[sys.argv[1]]()
