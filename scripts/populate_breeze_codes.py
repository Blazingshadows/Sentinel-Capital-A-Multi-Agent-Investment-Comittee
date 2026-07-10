"""Widens the Discovery universe's live-fetchable set by matching
`discovery/universe/nse_universe.json` symbols against ICICI's public NSE
security master, instead of hand-verifying each symbol's Breeze stock_code
one at a time.

The security master is the same ZIP `breeze_connect` itself downloads at
import time (config.SECURITY_MASTER_URL) -- a free, no-auth, no-per-symbol-
API-call download of every listed security. `NSEScripMaster.txt`'s
`ShortName` column is Breeze's stock_code; its last column (`ExchangeCode`)
is the NSE tradingsymbol. Restricted to Series=="EQ" to avoid picking up
warrants/bonds/rights entries that share a company's base symbol (e.g. an
"HDFCBANK" warrant row exists alongside the real equity row).

Symbols that have since been renamed or restructured (e.g. Tata Motors
demerging into separate passenger/commercial-vehicle listings) won't match
and are left with stock_code=null, same as today -- this only ever adds
codes, never removes or guesses one.

Usage:
    python scripts/populate_breeze_codes.py
"""

import csv
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SECURITY_MASTER_URL = "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip"
UNIVERSE_PATH = Path(__file__).resolve().parents[1] / "backend/committee/discovery/universe/nse_universe.json"


def fetch_nse_symbol_to_stock_code() -> dict[str, str]:
    resp = urllib.request.urlopen(SECURITY_MASTER_URL, timeout=30)
    zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    content = zf.read("NSEScripMaster.txt").decode("utf-8", errors="replace")

    reader = csv.reader(io.StringIO(content))
    next(reader)  # header
    mapping: dict[str, str] = {}
    for row in reader:
        if len(row) < 3:
            continue
        short_name, series, exch_code = row[1].strip(), row[2].strip(), row[-1].strip()
        if series == "EQ" and exch_code and short_name:
            mapping[exch_code] = short_name
    return mapping


def main() -> None:
    print("Downloading NSE security master...")
    nse_map = fetch_nse_symbol_to_stock_code()
    print(f"  {len(nse_map)} EQ-series symbols found.")

    universe = json.loads(UNIVERSE_PATH.read_text())
    entries = universe["symbols"] if isinstance(universe, dict) else universe

    matched, already_had, unmatched = 0, 0, []
    for entry in entries:
        if entry.get("stock_code"):
            already_had += 1
            continue
        code = nse_map.get(entry["symbol"])
        if code:
            entry["stock_code"] = code
            matched += 1
        else:
            unmatched.append(entry["symbol"])

    UNIVERSE_PATH.write_text(json.dumps(universe, indent=2) + "\n")

    total = len(entries)
    print(f"\n{matched} new stock_codes matched, {already_had} already had one, "
          f"{len(unmatched)} unmatched -- {matched + already_had}/{total} of the universe is now live-fetchable.")
    if unmatched:
        print(f"Unmatched (renamed/restructured/delisted, left as null): {', '.join(unmatched[:20])}"
              + (f" ... and {len(unmatched) - 20} more" if len(unmatched) > 20 else ""))


if __name__ == "__main__":
    main()
