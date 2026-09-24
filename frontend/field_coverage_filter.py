#!/usr/bin/env python3
"""
field_coverage_filter.py

Pre-sweep field screening for BRAIN Template Lab sweeps.

Fixes the -10.00 degenerate-fitness problem seen in Task 70 / "Winsorized
Peer Rank · ALL D1" by dropping fields *before* they ever hit a
group_rank(ts_rank(winsorize(field / cap), N), group) template:

  1. Flag / categorical / dummy fields (e.g. *_update_flag*, *_flag,
     is_*, has_*) — these are near-constant 0/1 series. Dividing by cap,
     winsorizing, then rank-transforming a near-zero-variance series is
     what produces the -10.00 sentinel.

  2. Fields with thin coverage in the target region/universe/delay —
     checked live against BRAIN's /data-fields endpoint. A field that's
     populated for only a fraction of the LARGE universe in ALL region
     will produce a mostly-NaN cross-section, which degenerates the same
     way.

Usage:
    python3 field_coverage_filter.py \
        --dataset-ids analyst10 sentiment21 \
        --region ALL --universe LARGE --delay 1 \
        --min-coverage 0.90 \
        --cookie-file ./brain_cookies.json \
        --out clean_fields.json

Auth:
    Reuses the same cookie-jar convention as alpha_engine_cookie_based_v21.py
    — a JSON file of {"name": ..., "value": ...} pairs, or a Netscape-format
    cookies.txt. Point --cookie-file at whatever your existing engine already
    logs in with; this script does not re-authenticate.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

BRAIN_API = "https://api.worldquantbrain.com"

# Field-name patterns that indicate binary / categorical / dummy fields.
# These should never go through ratio+winsorize+rank templates as-is.
FLAG_PATTERNS = [
    r"_flag$",
    r"_flag_",
    r"^is_",
    r"^has_",
    r"_indicator$",
    r"_dummy$",
    r"^update_flag",
    r"_update_flag",
    r"_binary$",
]
FLAG_RE = re.compile("|".join(FLAG_PATTERNS), re.IGNORECASE)


def load_cookies(cookie_file: str) -> dict:
    path = Path(cookie_file)
    if not path.exists():
        sys.exit(f"[!] Cookie file not found: {cookie_file}")

    text = path.read_text().strip()
    # JSON list of {"name": ..., "value": ...} dicts, or a flat {name: value} dict
    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        return {c["name"]: c["value"] for c in data}

    # Netscape cookies.txt fallback
    cookies = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    return cookies


def is_flag_field(field_id: str, description: str = "") -> bool:
    return bool(FLAG_RE.search(field_id) or FLAG_RE.search(description or ""))


def fetch_dataset_fields(session: requests.Session, dataset_id: str,
                          region: str, universe: str, delay: int,
                          limit: int = 200) -> list:
    """Page through /data-fields for one dataset and return raw field records."""
    fields = []
    offset = 0
    while True:
        params = {
            "dataset.id": dataset_id,
            "region": region,
            "universe": universe,
            "delay": delay,
            "limit": limit,
            "offset": offset,
        }
        resp = session.get(f"{BRAIN_API}/data-fields", params=params, timeout=30)
        if resp.status_code == 429:
            time.sleep(5)
            continue
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("results", payload.get("children", []))
        if not batch:
            break
        fields.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return fields


def extract_coverage(field: dict) -> float:
    """
    BRAIN field records carry coverage under different keys depending on
    dataset type ('coverage', 'coverage_pct', or nested under
    'metadata'). Normalize to a 0-1 float; default to 1.0 (assume full
    coverage) only when no coverage signal is present at all, so a field
    is never dropped on a lookup miss alone.
    """
    for key in ("coverage", "coveragePct", "coverage_pct"):
        val = field.get(key)
        if val is not None:
            return val / 100.0 if val > 1 else float(val)
    metadata = field.get("metadata") or {}
    val = metadata.get("coverage")
    if val is not None:
        return val / 100.0 if val > 1 else float(val)
    return 1.0


def screen_fields(session: requests.Session, dataset_ids: list, region: str,
                   universe: str, delay: int, min_coverage: float) -> dict:
    kept, dropped_flag, dropped_coverage = [], [], []

    for ds in dataset_ids:
        print(f"[*] Fetching fields for dataset={ds} region={region} "
              f"universe={universe} delay={delay} ...", file=sys.stderr)
        try:
            records = fetch_dataset_fields(session, ds, region, universe, delay)
        except requests.HTTPError as e:
            print(f"[!] Failed to fetch {ds}: {e}", file=sys.stderr)
            continue

        for f in records:
            fid = f.get("id", "")
            desc = f.get("description", "")

            if is_flag_field(fid, desc):
                dropped_flag.append({"id": fid, "description": desc, "dataset": ds})
                continue

            cov = extract_coverage(f)
            if cov < min_coverage:
                dropped_coverage.append({
                    "id": fid, "description": desc, "dataset": ds, "coverage": cov
                })
                continue

            kept.append({"id": fid, "description": desc, "dataset": ds, "coverage": cov})

    return {"kept": kept, "dropped_flag": dropped_flag, "dropped_coverage": dropped_coverage}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset-ids", nargs="+", required=True,
                     help="Dataset IDs to screen, e.g. analyst10 sentiment21")
    ap.add_argument("--region", default="ALL")
    ap.add_argument("--universe", default="LARGE")
    ap.add_argument("--delay", type=int, default=1)
    ap.add_argument("--min-coverage", type=float, default=0.90,
                     help="Minimum fraction (0-1) of the universe the field "
                          "must be populated for. Default 0.90.")
    ap.add_argument("--cookie-file", required=True,
                     help="Path to the cookie jar your alpha engine already logs in with")
    ap.add_argument("--out", default="clean_fields.json",
                     help="Where to write the surviving field-id list (for the template sweep)")
    ap.add_argument("--report", default="screen_report.json",
                     help="Where to write the full kept/dropped breakdown")
    args = ap.parse_args()

    cookies = load_cookies(args.cookie_file)
    session = requests.Session()
    session.cookies.update(cookies)

    result = screen_fields(
        session, args.dataset_ids, args.region, args.universe,
        args.delay, args.min_coverage,
    )

    clean_ids = [f["id"] for f in result["kept"]]
    Path(args.out).write_text(json.dumps(clean_ids, indent=2))
    Path(args.report).write_text(json.dumps(result, indent=2))

    print(f"\n[✓] Kept:              {len(result['kept'])}")
    print(f"[✓] Dropped (flag):    {len(result['dropped_flag'])}")
    print(f"[✓] Dropped (coverage):{len(result['dropped_coverage'])}")
    print(f"[✓] Clean field list → {args.out}")
    print(f"[✓] Full report      → {args.report}")

    if result["dropped_flag"]:
        print("\nSample dropped flag fields:", file=sys.stderr)
        for f in result["dropped_flag"][:5]:
            print(f"  - {f['id']}  ({f['dataset']})", file=sys.stderr)

    if result["dropped_coverage"]:
        print("\nSample dropped low-coverage fields:", file=sys.stderr)
        for f in result["dropped_coverage"][:5]:
            print(f"  - {f['id']}  coverage={f['coverage']:.2f}  ({f['dataset']})",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
