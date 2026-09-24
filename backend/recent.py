"""List the last 10 alphas with Sharpe, to identify one by metric."""
from __future__ import annotations
import asyncio, os
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


async def main():
    c = BrainClient(); e = BrainEndpoints(c)
    c.load_cookies(parse_cookie(os.environ["BRAIN_COOKIE"]))
    r = await e.client.request(
        "GET", "/users/self/alphas?limit=20&order=-dateCreated",
        version="4.0", raise_for_status=False,
    )
    body = r.body if isinstance(r.body, dict) else {}
    rows = body.get("results") or []
    print(f"{'id':12s}  {'region':5s}  {'univ':9s}  {'sharpe':>7s}  {'fit':>5s}  {'turn':>6s}  created")
    for a in rows:
        s = (a.get("is") or {})
        st = a.get("settings") or {}
        print(
            f"{a.get('id'):12s}  {st.get('region','-'):5s}  {st.get('universe','-'):9s}"
            f"  {s.get('sharpe'):>7}  {s.get('fitness'):>5}  {s.get('turnover'):>6}"
            f"  {a.get('dateCreated','')[:19]}"
        )


if __name__ == "__main__":
    asyncio.run(main())
