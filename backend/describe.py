import asyncio, os
from alpha_harness.brain.client import BrainClient
from alpha_harness.brain.endpoints import BrainEndpoints

ALPHA_ID = "qMxl5kxK"

DESCRIPTION = (
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
    client = BrainClient()
    endpoints = BrainEndpoints(client)
    cookie = os.environ.get("BRAIN_COOKIE")
    if not cookie:
        cookie = input("cookie: ").strip()
        if not cookie.startswith("t="):
            cookie = "t=" + cookie
    client.load_cookies(parse_cookie(cookie))

    st = await endpoints.get_auth()
    if st is None or st.user_id is None:
        print("✗ cookie rejected"); return
    print(f"✓ signed in as {st.user_id}")

    body = await endpoints.update_alpha(ALPHA_ID, {"description": DESCRIPTION})
    print(f"✓ description set ({len(DESCRIPTION)} chars)")
    print("  preview:", (body.get("description") or "")[:80], "…")


asyncio.run(main())
