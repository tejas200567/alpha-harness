import asyncio, os
from alpha_harness.brain.client import BrainClient
from alpha_harness.brain.endpoints import BrainEndpoints

ALPHA_ID = "qMxl5kxK"
DESC = (
    "Mean-reversion alpha on GBR/TOP700 combining a 15-day relative-strength "
    "factor with a 252-day scaled imbalance score. Both legs are backfilled and "
    "winsorized at 4 sigma, then multiplied and neutralized against sector to "
    "remove sector bets. Trades at 25% turnover with a 5-day decay, producing a "
    "Sharpe of 2.74 and fitness of 1.72 in-sample."
)


def parse_cookie(raw):
    out = []
    for part in raw.split(";"):
        p = part.strip()
        if not p or "=" not in p: continue
        n, _, v = p.partition("=")
        out.append({"name": n.strip(), "value": v.strip(),
                    "domain": ".worldquantbrain.com", "path": "/"})
    return out


async def main():
    c = BrainClient(); e = BrainEndpoints(c)
    c.load_cookies(parse_cookie(os.environ["BRAIN_COOKIE"]))

    for payload in [
        {"description": DESC},                # what we tried
        {"regular": {"description": DESC}},   # nested under regular
        {"name": "qMxl5kxK test"},            # name only, does PATCH work at all?
    ]:
        r = await c.request("PATCH", f"/alphas/{ALPHA_ID}", json_body=payload,
                            raise_for_status=False)
        print(f"--- payload keys: {list(payload)}")
        print(f"    status: {r.status}")
        print(f"    body:   {r.body}")


asyncio.run(main())
