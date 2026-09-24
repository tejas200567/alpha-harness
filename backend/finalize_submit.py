"""Clear the test name and submit qMxl5kxK (with explicit confirmation)."""
from __future__ import annotations
import asyncio, os, sys
from alpha_harness.brain.client import BrainClient
from alpha_harness.brain.endpoints import BrainEndpoints

ALPHA_ID = "qMxl5kxK"


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

    st = await e.get_auth()
    if st is None or st.user_id is None:
        print("✗ cookie rejected"); return
    print(f"✓ signed in as {st.user_id}")

    # 1. Clear the test name
    r = await c.request("PATCH", f"/alphas/{ALPHA_ID}",
                        json_body={"name": ""}, raise_for_status=False)
    print(f"  name cleared: HTTP {r.status}")

    # 2. Fetch and print the IS checks one more time
    alpha = await e.get_alpha(ALPHA_ID)
    s = alpha.in_sample
    if s:
        print(f"\n  Sharpe   {s.sharpe}")
        print(f"  Fitness  {s.fitness}")
        print(f"  Turnover {s.turnover}")
        print(f"  Returns  {s.returns}")
    print(f"  Stage    {alpha.stage}")
    print(f"  Status   {alpha.status}")
    if s:
        passes = sum(1 for ck in s.checks if ck.result == "PASS")
        warns  = sum(1 for ck in s.checks if ck.result == "WARNING")
        pend   = sum(1 for ck in s.checks if ck.result == "PENDING")
        fails  = sum(1 for ck in s.checks if ck.result == "FAIL")
        print(f"  Checks: {passes} PASS, {warns} WARNING, {fails} FAIL, {pend} PENDING")

    # 3. Confirm + submit
    print()
    answer = input(f"Type SUBMIT to submit {ALPHA_ID} (irreversible): ").strip()
    if answer != "SUBMIT":
        print("aborted"); return

    r = await c.request("POST", f"/alphas/{ALPHA_ID}/submit", raise_for_status=False)
    print(f"\nsubmit response: HTTP {r.status}")
    print(r.body)


if __name__ == "__main__":
    asyncio.run(main())
