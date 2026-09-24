"""Attempt submit. Prints BRAIN's full check response (including the 403 body)."""
from __future__ import annotations
import asyncio, os, sys
from alpha_harness.brain.client import BrainClient
from alpha_harness.brain.endpoints import BrainEndpoints


def parse_cookie(raw):
    out = []
    for p in raw.split(";"):
        p = p.strip()
        if not p or "=" not in p: continue
        n, _, v = p.partition("=")
        out.append({"name": n.strip(), "value": v.strip(),
                    "domain": ".worldquantbrain.com", "path": "/"})
    return out


async def main(aid: str):
    c = BrainClient(); e = BrainEndpoints(c)
    c.load_cookies(parse_cookie(os.environ["BRAIN_COOKIE"]))
    r = await c.request("POST", f"/alphas/{aid}/submit", raise_for_status=False)
    print(f"HTTP {r.status}")
    body = r.body if isinstance(r.body, dict) else {}
    checks = ((body.get("is") or {}).get("checks")) or []
    for ck in checks:
        if ck.get("name") in ("IS_LADDER_SHARPE", "REGULAR_SUBMISSION",
                              "SELF_CORRELATION", "PROD_CORRELATION",
                              "POWER_POOL_CORRELATION"):
            print(f"  {ck['name']:26s} {ck.get('result','?'):8s}"
                  f" value={ck.get('value')} limit={ck.get('limit')}")
    if r.status >= 400:
        print("  (submit refused — alpha unchanged)")


if __name__ == "__main__":
    aid = sys.argv[1] if len(sys.argv) > 1 else input("alpha id: ").strip()
    asyncio.run(main(aid))
