#!/usr/bin/env python3
"""Interactive BRAIN Alpha submitter — prompts for cookie, market, settings, expression."""
from __future__ import annotations
import asyncio, getpass, os
from alpha_harness.brain.client import BrainClient
from alpha_harness.brain.endpoints import BrainEndpoints

FINAL = {"COMPLETE", "WARNING", "ERROR", "TIMEOUT", "FAIL", "CANCELLED"}


def parse_cookie(raw: str):
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        n, _, v = part.partition("=")
        out.append({"name": n.strip(), "value": v.strip(),
                    "domain": ".worldquantbrain.com", "path": "/"})
    return out


def read_multiline(hint: str) -> str:
    print(hint)
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


def ask(label: str, default):
    raw = input(f"{label} [{default}]: ").strip()
    if not raw:
        return default
    return raw


async def run(cookie, expression, region, universe, decay, neutralization,
              truncation, delay):
    is_py = "from brain.alphas" in expression or "@alpha" in expression

    settings = {
        "instrumentType": "EQUITY",
        "region": region,
        "universe": universe,
        "delay": delay,
        "decay": decay,
        "neutralization": neutralization,
        "truncation": truncation,
        "pasteurization": "ON",
        "language": "PYTHON" if is_py else "FASTEXPR",
        "visualization": False,
        "testPeriod": "P2Y0M0D",
    }
    if is_py:
        settings["lookback"] = 25
    else:
        settings["unitHandling"] = "VERIFY"
        settings["nanHandling"] = "ON"

    client = BrainClient()
    endpoints = BrainEndpoints(client)
    client.load_cookies(parse_cookie(cookie))

    state = await endpoints.get_auth()
    if state is None or state.user_id is None:
        print("✗ cookie rejected — copy a fresh t= from the browser")
        return
    print(f"✓ signed in as {state.user_id}")

    payload = {"type": "REGULAR", "settings": settings, "regular": expression}
    r = await client.request("POST", "/simulations", json_body=payload,
                             raise_for_status=False)
    if r.status != 201:
        print(f"✗ submit failed: HTTP {r.status}")
        print(r.body)
        return

    hdrs = getattr(r, "headers", None) or {}
    loc = hdrs.get("Location") or hdrs.get("location")
    if not loc:
        print("✗ no Location header:", r.body)
        return
    sim_id = loc.rstrip("/").split("/")[-1]
    print(f"→ simulation {sim_id}")

    while True:
        r = await endpoints.read_simulation(sim_id)
        body = r.body if isinstance(r.body, dict) else {}
        st = body.get("status")
        if st:
            print(f"  {st}")
        if st in FINAL:
            if st != "COMPLETE":
                print("final body:", body)
                return
            aid = body.get("alpha")
            print(f"\n✓ alpha id: {aid}")
            if aid:
                a = await endpoints.get_alpha(aid)
                s = a.in_sample
                if s:
                    print(f"  Sharpe   {s.sharpe}")
                    print(f"  Fitness  {s.fitness}")
                    print(f"  Turnover {s.turnover}")
                    print(f"  Returns  {s.returns}")
                    print(f"  Drawdown {s.drawdown}")
                print(f"  Stage    {a.stage}")
                print(f"  Status   {a.status}")
            return
        await asyncio.sleep(5)


async def main():
    print("── BRAIN Alpha Submitter ──\n")
    cookie = os.environ.get("BRAIN_COOKIE") or getpass.getpass("cookie (t=...): ").strip()
    if not cookie:
        print("✗ no cookie"); return
    if not cookie.startswith("t=") and "=" not in cookie:
        cookie = "t=" + cookie

    region = input("region [USA]: ").strip().upper() or "USA"
    default_uni = {"USA": "TOP3000", "EUR": "TOP2500",
                   "GBR": "TOP700", "DEU": "TOP500"}.get(region, "TOP3000")
    universe = input(f"universe [{default_uni}]: ").strip().upper() or default_uni
    delay = int(ask("delay", 1))
    decay = int(ask("decay", 5 if region in ("GBR", "DEU") else 10))
    neutralization = ask("neutralization", "STATISTICAL" if region == "GBR" else "MARKET").upper()
    truncation = float(ask("truncation", 0.08))

    expression = read_multiline("\nExpression:")
    if not expression.strip():
        print("✗ empty expression"); return

    print(f"\nsubmitting to {region}/{universe}  "
          f"decay={decay}  neut={neutralization}  trunc={truncation}  delay={delay}")
    await run(cookie, expression, region, universe, decay, neutralization,
              truncation, delay)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\naborted")
