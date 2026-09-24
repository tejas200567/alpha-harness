"""GBR/TOP700 preset submitter — prompts for expression only."""
from __future__ import annotations
import asyncio, getpass, os
from alpha_harness.brain.client import BrainClient
from alpha_harness.brain.endpoints import BrainEndpoints

FINAL = {"COMPLETE", "WARNING", "ERROR", "TIMEOUT", "FAIL", "CANCELLED"}

PRESET = {
    "instrumentType": "EQUITY",
    "region": "GBR",
    "universe": "TOP700",
    "delay": 1,
    "decay": 5,
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


def read_expr():
    print("Expression:")
    print("(paste, then a line with a single '.' to submit)")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    return "\n".join(lines)


async def main():
    cookie = os.environ.get("BRAIN_COOKIE") or getpass.getpass("cookie: ").strip()
    if not cookie.startswith("t=") and "=" not in cookie:
        cookie = "t=" + cookie

    expr = read_expr().strip()
    if not expr:
        print("✗ empty expression"); return

    client = BrainClient(); endpoints = BrainEndpoints(client)
    client.load_cookies(parse_cookie(cookie))

    st = await endpoints.get_auth()
    if st is None or st.user_id is None:
        print("✗ cookie rejected"); return
    print(f"✓ {st.user_id}  →  GBR/TOP700  decay=5  STATISTICAL")

    payload = {"type": "REGULAR", "settings": PRESET, "regular": expr}
    r = await client.request("POST", "/simulations", json_body=payload,
                             raise_for_status=False)
    if r.status != 201:
        print(f"✗ submit failed HTTP {r.status}:", r.body); return

    hdrs = getattr(r, "headers", None) or {}
    loc = hdrs.get("Location") or hdrs.get("location")
    sim_id = loc.rstrip("/").split("/")[-1]
    print(f"→ simulation {sim_id}")

    while True:
        r = await endpoints.read_simulation(sim_id)
        body = r.body if isinstance(r.body, dict) else {}
        s = body.get("status")
        if s: print(f"  {s}")
        if s in FINAL:
            if s != "COMPLETE":
                print("final:", body); return
            aid = body.get("alpha")
            a = await endpoints.get_alpha(aid)
            ins = a.in_sample
            print(f"\n✓ alpha id: {aid}")
            if ins:
                print(f"  Sharpe   {ins.sharpe}")
                print(f"  Fitness  {ins.fitness}")
                print(f"  Turnover {ins.turnover}")
                print(f"  Returns  {ins.returns}")
                for ck in ins.checks:
                    if ck.name in ("IS_LADDER_SHARPE", "REGULAR_SUBMISSION",
                                   "LOW_SHARPE", "LOW_FITNESS"):
                        print(f"  {ck.name}: {ck.result}  value={ck.value}  limit={ck.limit}")
            return
        await asyncio.sleep(5)


asyncio.run(main())
