"""Poll an alpha's checks to resolution. Alpha id from argv or prompt."""
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
    for _ in range(20):
        a = await e.get_alpha(aid)
        s = a.in_sample
        if s:
            print(f"--- {aid}  stage={a.stage}  status={a.status}")
            for ck in s.checks:
                if ck.name in (
                    "IS_LADDER_SHARPE",
                    "REGULAR_SUBMISSION",
                    "SELF_CORRELATION",
                    "PROD_CORRELATION",
                    "POWER_POOL_CORRELATION",
                ):
                    print(f"  {ck.name:26s} {ck.result:8s} value={ck.value} limit={ck.limit}")
            if not any(c.result == "PENDING" for c in s.checks):
                return
        await asyncio.sleep(8)


if __name__ == "__main__":
    aid = sys.argv[1] if len(sys.argv) > 1 else input("alpha id: ").strip()
    asyncio.run(main(aid))
