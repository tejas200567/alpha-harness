"""Scoring a region-agnostic (RA) simulation from its parent's submission check.

An RA parent carries no in-sample statistics of its own, so objectives.extract scores
every one as FAILURE. What judges it is GET /alphas/{parent}/check: BRAIN applies the
"at least two children pass" rule itself (MIN_SUBMITTABLE_CHILDREN) and lists each
child's checks under is.subregions, keyed by child alpha id. /check on a child answers
400, so the parent's body is the only source.

The Optuna value is the second-best child's gate ratio: per child, the worst of
value / limit over Sharpe, Fitness and 2Y Sharpe, so 1.0 or more clears all three.
Second-best mirrors the two-children rule and gives the sampler a gradient below the
pass line instead of a flat failure.
"""

from __future__ import annotations

import math
from typing import Any

from .objectives import FAILURE, Objective

#: The cheap gates every RA child must clear, by check name.
GATES = ("LOW_SHARPE", "LOW_FITNESS", "LOW_2Y_SHARPE")
#: BRAIN's own two-children rule, reported on the parent.
MIN_CHILDREN = "MIN_SUBMITTABLE_CHILDREN"


def _number(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def parent_checks(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    checks = ((body or {}).get("is") or {}).get("checks") or []
    return [c for c in checks if isinstance(c, dict)]


def children(body: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Child alpha id -> that child's checks."""
    subregions = ((body or {}).get("is") or {}).get("subregions") or {}
    return {k: v for k, v in subregions.items() if isinstance(v, list)}


def child_ratio(checks: list[dict[str, Any]]) -> float | None:
    """The worst value / limit over the gates; None when no gate carries numbers."""
    by_name = {c.get("name"): c for c in checks if isinstance(c, dict)}
    ratios: list[float] = []
    for name in GATES:
        check = by_name.get(name) or {}
        value, limit = _number(check.get("value")), _number(check.get("limit"))
        if value is None or limit is None or limit <= 0:
            continue
        ratios.append(value / limit)
    return min(ratios) if ratios else None


def score(body: dict[str, Any] | None) -> float:
    """The second-best child's ratio. One child can never be submitted, so it scores
    below its own ratio and below zero."""
    found = (child_ratio(c) for c in children(body).values())
    ratios = sorted((r for r in found if r is not None), reverse=True)
    if not ratios:
        return FAILURE
    if len(ratios) == 1:
        return min(ratios[0], 0.0) - 1.0
    return ratios[1]


def constraints(body: dict[str, Any] | None) -> dict[str, float]:
    """Optuna's convention: 0.0 when feasible, else how many children short."""
    for check in parent_checks(body):
        if check.get("name") != MIN_CHILDREN:
            continue
        if check.get("result") == "PASS":
            return {MIN_CHILDREN: 0.0}
        value, limit = _number(check.get("value")), _number(check.get("limit"))
        if value is None or limit is None:
            return {MIN_CHILDREN: 1.0}
        return {MIN_CHILDREN: max(0.0, limit - value)}
    # No verdict is not a pass.
    return {MIN_CHILDREN: 1.0}


def values(body: dict[str, Any] | None, objectives: list[Objective]) -> list[float]:
    """One number per objective, as objectives.extract returns: the RA score for each."""
    s = score(body)
    return [s for _ in objectives]


def summarise(alpha_id: str, body: dict[str, Any] | None) -> dict[str, Any]:
    """The trial row the UI shows, shaped like objectives.summarise, plus the children."""
    violations = constraints(body)
    detail = []
    for check in parent_checks(body):
        name = check.get("name")
        failed = 1.0 if check.get("result") == "FAIL" else 0.0
        detail.append(
            {
                "name": name,
                "key": name,
                "result": check.get("result"),
                "value": check.get("value"),
                "limit": check.get("limit"),
                "violation": violations.get(name, failed),
            }
        )
    per_child = {
        child_id: {
            "ratio": child_ratio(checks),
            "failedChecks": sorted(
                {c["name"] for c in checks if c.get("result") == "FAIL" and c.get("name")}
            ),
            "pyramids": [
                p.get("name")
                for c in checks
                if c.get("name") == "MATCHES_PYRAMID"
                for p in c.get("pyramids") or []
            ],
        }
        for child_id, checks in children(body).items()
    }
    return {
        "alphaId": alpha_id,
        "grade": None,
        "stats": None,
        "checks": detail,
        "constraint": violations,
        "feasible": all(v <= 0.0 for v in violations.values()),
        "failedChecks": [d["name"] for d in detail if d["violation"] > 0],
        "regionAgnostic": {"score": score(body), "children": per_child},
    }
