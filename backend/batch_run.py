"""Batch submit FASTEXPR alphas from a file. One expression per line."""
from __future__ import annotations
import asyncio, os, sys, time
from pathlib import Path
from alpha_harness.brain.client import BrainClient
from alpha_harness.brain.endpoints import BrainEndpoints

FINAL = {"COMPLETE", "WARNING", "ERROR", "TIMEOUT", "FAIL", "CANCELLED"}

# GBR/TOP700 preset (override with region/universe args if you want)
SETTINGS = {
    "instrumentType": "EQUITY",
    "region": "GBR",
    "universe": "TOP700",
    "delay": 1,
    "decay": 20,
    "neutralization": "STATISTICAL",
    "truncation": 0.08,
    "pasteurization": "ON",
    "language": "FASTEXPR",
    "visualization": False,
    "testPeriod": "P2Y0M0D",
    "unitHandling": "VERIFY",
    "nanHandling": "ON",
}


def parse_cookie(raw):
    out = []
    for p in raw.split(";"):
        p = p.strip()
        if not p or "=" not in p: continue
        n, _, v = p.partition("=")
        out.append({"name": n.strip(), "value": v.strip(),
                    "domain": ".worldquantbrain.com", "path": "/"})
    return out


def read_batch(path: Path) -> list[str]:
    exprs = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        exprs.append(line)
    return exprs


async def submit_one(client, expr):
    payload = {"type": "REGULAR", "settings": SETTINGS, "regular": expr}
    r = await client.request("POST", "/simulations", json_body=payload,
                             raise_for_status=False)
    if r.status != 201:
        return {"expr": expr, "sim_id": None, "error": f"HTTP {r.status} {r.body}"}
    hdrs = getattr(r, "headers", None) or {}
    loc = hdrs.get("Location") or hdrs.get("location") or ""
    sim_id = loc.rstrip("/").split("/")[-1]
    return {"expr": expr, "sim_id": sim_id, "error": None}


async def poll_one(endpoints, sim_id):
    while True:
        r = await endpoints.read_simulation(sim_id)
        body = r.body if isinstance(r.body, dict) else {}
        st = body.get("status")
        if st in FINAL:
            if st != "COMPLETE":
                return {"alpha_id": None, "status": st}
            return {"alpha_id": body.get("alpha"), "status": st}
        await asyncio.sleep(4)


async def main(batch_path: Path):
    client = BrainClient(); endpoints = BrainEndpoints(client)
    client.load_cookies(parse_cookie(os.environ["BRAIN_COOKIE"]))

    st = await endpoints.get_auth()
    if st is None or st.user_id is None:
        print("✗ cookie rejected"); return
    print(f"✓ {st.user_id}")

    exprs = read_batch(batch_path)
    print(f"loaded {len(exprs)} expressions from {batch_path.name}\n")

    # 1. Submit all sequentially (fast, avoids burst rate-limit)
    submitted = []
    for i, expr in enumerate(exprs, 1):
        info = await submit_one(client, expr)
        tag = info["sim_id"] or "FAILED"
        short = expr[:60] + ("…" if len(expr) > 60 else "")
        print(f"  [{i:2d}/{len(exprs)}] {tag:30s}  {short}")
        submitted.append(info)
        await asyncio.sleep(1.5)  # stay under rate limit

    # 2. Poll all in parallel
    print(f"\npolling {sum(1 for s in submitted if s['sim_id'])} sims…")
    tasks = []
    for s in submitted:
        if s["sim_id"]:
            tasks.append(poll_one(endpoints, s["sim_id"]))
        else:
            async def failed(s=s): return {"alpha_id": None, "status": "SUBMIT_FAILED"}
            tasks.append(failed())
    results = await asyncio.gather(*tasks)

    # 3. Fetch each alpha and print a table
    print(f"\n{'idx':>3s}  {'alpha':10s}  {'sharpe':>7s}  {'fitness':>8s}  "
          f"{'turn':>7s}  {'returns':>8s}  expr")
    print("-" * 100)
    ok = []
    for i, (s, res) in enumerate(zip(submitted, results), 1):
        aid = res.get("alpha_id")
        expr_short = s["expr"][:40] + ("…" if len(s["expr"]) > 40 else "")
        if not aid:
            print(f"{i:3d}  {'-':10s}  {'-':>7s}  {'-':>8s}  {'-':>7s}  {'-':>8s}  {expr_short}")
            continue
        a = await endpoints.get_alpha(aid)
        ins = a.in_sample
        if ins:
            print(f"{i:3d}  {aid:10s}  {str(ins.sharpe):>7s}  {str(ins.fitness):>8s}  "
                  f"{str(ins.turnover):>7s}  {str(ins.returns):>8s}  {expr_short}")
            ok.append((aid, ins.sharpe))
        else:
            print(f"{i:3d}  {aid:10s}  {'?':>7s}  {'?':>8s}  {'?':>7s}  {'?':>8s}  {expr_short}")

    # 4. Top by Sharpe
    ok.sort(key=lambda x: -(x[1] or -99))
    if ok:
        print(f"\nTop by Sharpe:")
        for aid, sh in ok[:5]:
            print(f"  {aid}   sharpe={sh}   → submit via: uv run python try_submit.py {aid}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("batch.txt")
    asyncio.run(main(path))
