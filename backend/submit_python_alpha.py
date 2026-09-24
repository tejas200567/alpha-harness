"""Submit ts_rank_rank_returns.py to BRAIN as a Python Alpha, then poll."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from alpha_harness.brain.client import BrainClient
from alpha_harness.brain.endpoints import BrainEndpoints

ALPHA_FILE = Path(__file__).parent / "ts_rank_rank_returns.py"
FINAL = {"COMPLETE", "WARNING", "ERROR", "TIMEOUT", "FAIL", "CANCELLED"}

SETTINGS = {
    "instrumentType": "EQUITY",
    "region": "EUR",
    "universe": "TOP2500",
    "delay": 1,
    "decay": 10,
    "neutralization": "MARKET",
    "truncation": 0.8,
    "pasteurization": "ON",
    "language": "PYTHON",
    "lookback": 25,
    "visualization": False,
    "testPeriod": "P2Y0M0D",
}


def parse_cookie(raw: str) -> list[dict[str, str]]:
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        out.append({"name": name.strip(), "value": value.strip(),
                    "domain": ".worldquantbrain.com", "path": "/"})
    return out


def _location(resp) -> str:
    for attr in ("location", "Location"):
        val = getattr(resp, attr, None)
        if val:
            return str(val)
    hdrs = getattr(resp, "headers", None) or {}
    for key in ("Location", "location"):
        if key in hdrs:
            return str(hdrs[key])
    raise RuntimeError(f"no Location header on response: {resp!r}")


async def main() -> None:
    client = BrainClient()
    endpoints = BrainEndpoints(client)
    client.load_cookies(parse_cookie(os.environ["BRAIN_COOKIE"]))

    # Confirm session is alive before spending quota
    state = await endpoints.get_auth()
    if state is None or state.user_id is None:
        raise SystemExit("session not valid — refresh the cookie")
    print(f"session: user_id={state.user_id}")

    payload = {
        "type": "REGULAR",
        "settings": SETTINGS,
        "regular": ALPHA_FILE.read_text(),
    }
    start = await client.request("POST", "/simulations", json_body=payload,
                                 raise_for_status=False)
    if start.status != 201:
        print("submit failed:", start.status, start.body)
        return

    sim_id = _location(start).rstrip("/").split("/")[-1]
    print(f"submitted: simulation {sim_id}")

    while True:
        r = await endpoints.read_simulation(sim_id)
        body = r.body if isinstance(r.body, dict) else {}
        status = body.get("status")
        print(f"  status={status}")
        if status in FINAL:
            if status != "COMPLETE":
                print("final body:", body)
                return
            alpha_id = body.get("alpha")
            print(f"alpha id: {alpha_id}")
            if not alpha_id:
                print("full body:", body)
                return

            alpha = await endpoints.get_alpha(alpha_id)
            s = alpha.in_sample
            print()
            print("=== in-sample stats ===")
            if s:
                print(f"  sharpe    : {s.sharpe}")
                print(f"  fitness   : {s.fitness}")
                print(f"  turnover  : {s.turnover}")
                print(f"  returns   : {s.returns}")
                print(f"  drawdown  : {s.drawdown}")
                print(f"  margin    : {s.margin}")
            print()
            print("=== alpha ===")
            print(f"  id        : {alpha.id}")
            print(f"  name      : {alpha.name}")
            print(f"  type      : {alpha.type}")
            print(f"  grade     : {alpha.grade}")
            print(f"  stage     : {alpha.stage}")
            print(f"  status    : {alpha.status}")
            return
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
