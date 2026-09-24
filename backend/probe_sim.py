"""Send a PYTHON simulation with a raw dict — no Pydantic coercion."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from alpha_harness.brain.client import BrainClient
from alpha_harness.brain.endpoints import BrainEndpoints

ALPHA_FILE = Path(__file__).parent / "ts_rank_rank_returns.py"


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


async def main() -> None:
    client = BrainClient()
    endpoints = BrainEndpoints(client)
    client.load_cookies(parse_cookie(os.environ["BRAIN_COOKIE"]))

    payload = {
        "type": "REGULAR",
        "settings": {
            "instrumentType": "EQUITY",
            "region": "USA",
            "universe": "TOP3000",
            "delay": 1,
            "decay": 10,
            "neutralization": "MARKET",
            "truncation": 0.8,
            "pasteurization": "ON",
            "language": "PYTHON",
            "lookback": 25,
            "visualization": False,
            "testPeriod": "P2Y0M0D",
        },
        "regular": ALPHA_FILE.read_text(),
    }

    print("=== settings we're sending ===")
    print(json.dumps(payload["settings"], indent=2))
    print()

    r = await client.request("POST", "/simulations", json_body=payload,
                             raise_for_status=False)
    print("HTTP status:", r.status)
    hdrs = getattr(r, "headers", {}) or {}
    print("Location:", hdrs.get("Location") or hdrs.get("location"))
    print("body:", json.dumps(r.body, indent=2) if isinstance(r.body, dict)
          else r.body)


if __name__ == "__main__":
    asyncio.run(main())
