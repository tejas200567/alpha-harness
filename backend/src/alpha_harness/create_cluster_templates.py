"""
Cluster Alpha templates from the WQ community research post (Moskowitz &
Grinblatt 1999 industry momentum; Moskowitz/Ooi/Pedersen 2012 time-series
momentum). Uses the {"kind":"data","name":"cap"} literal-field node found
in labs/template.py's resolver.
"""
import requests

BASE = "http://localhost:8000"
HEADERS = {"x-harness-client": "1"}

def field(tag="A"):
    return {"kind": "var", "name": "FIELD", "tag": tag}

def group(tag="A"):
    return {"kind": "var", "name": "GROUP", "tag": tag}

def cap():
    return {"kind": "data", "name": "cap"}

def op(names, *args):
    return {"kind": "op", "ops": names if isinstance(names, list) else [names], "args": list(args)}

TEMPLATES = [
    {
        "name": "Industry Rotation",
        "description": "Ranks industries by their cap-weighted momentum -- long strong industries, short weak ones. Moskowitz & Grinblatt 1999.",
        "tree": {"version": 1, "root": op("rank",
            op("group_mean",
                op("ts_delta", field(), {"kind": "var", "name": "LOOKBACK", "tag": "A"}),
                cap(),
                group()))},
    },
    {
        "name": "Industry Timing",
        "description": "Trend-to-volatility of each industry's cap-weighted aggregate, scored across industries. Moskowitz, Ooi & Pedersen 2012.",
        "tree": {"version": 1, "root": op("rank",
            op("divide",
                op("ts_mean", op("group_mean", field(), cap(), group()), {"kind": "var", "name": "FAST_LOOKBACK", "tag": "A"}),
                op("ts_std_dev", op("group_mean", field(), cap(), group()), {"kind": "var", "name": "SLOW_LOOKBACK", "tag": "A"})))},
    },
    {
        "name": "Industry Abnormality",
        "description": "How far each industry's cap-weighted aggregate sits from its own recent history.",
        "tree": {"version": 1, "root": op("rank",
            op("ts_zscore",
                op("group_mean", field(), cap(), group()),
                {"kind": "var", "name": "LOOKBACK", "tag": "A"}))},
    },
    {
        "name": "Cluster Aggregate Rank",
        "description": "Collapses a field to one cap-weighted value per industry, then ranks industries against each other.",
        "tree": {"version": 1, "root": op("rank",
            op("group_mean", field(), cap(), group()))},
    },
]

def collect_ops(node, found):
    if node.get("kind") == "op":
        found.update(node.get("ops", []))
        for a in node.get("args", []):
            collect_ops(a, found)
    return found

def main():
    opts = requests.get(f"{BASE}/api/template-lab/options").json()
    available = {o["name"] for o in opts.get("blocks", [])}
    print(f"{len(available)} operators available\n")

    for t in TEMPLATES:
        used = collect_ops(t["tree"]["root"], set())
        missing = used - available
        if missing:
            print(f"SKIP  {t['name']}: missing operators {sorted(missing)}")
            continue
        r = requests.post(f"{BASE}/api/template-lab/templates", json=t, headers=HEADERS)
        if r.status_code in (200, 201):
            print(f"OK    {t['name']}")
        else:
            print(f"FAIL  {t['name']}: {r.status_code} {r.text[:300]}")

if __name__ == "__main__":
    main()
