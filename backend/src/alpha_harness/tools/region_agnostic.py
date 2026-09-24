"""Region-Agnostic Alpha: one expression, one RA universe, four regions at once.

An RAA request carries ``region="ALL"``; BRAIN fans it out per-region and returns one
RA Parent Alpha with up to four RA Children. The parent holds name/description; the
children are what submission judges — at least two must pass Sharpe >= 1.58,
Fitness >= 1.0, and the 2Y ladder Sharpe test.

Universes are sized, not named by region: SMALL / MEDIUM / LARGE map to a fixed
per-region tuple (see ``UNIVERSE_MAP``). Fields must intersect across at least two
regions or the request is rejected before it is sent.

Delay is D1 only. Concurrent quota counts the sum of the children's slots, so a
preview must report ``children`` — the scheduler reserves that many, not one.
"""

from __future__ import annotations

from typing import Any

from ..brain.schemas import (
    REGION_AGNOSTIC_REGION,
    SimulationRequest,
    SimulationSettings,
)

#: RAA universes, smallest to largest.
UNIVERSES = ("SMALL", "MEDIUM", "LARGE")

#: What each RA universe actually means, per region, for the detail card.
UNIVERSE_MAP: dict[str, dict[str, str]] = {
    "LARGE": {"USA": "TOP3000", "EUR": "TOP2500", "ASI": "MINVOL1M", "GLB": "MINVOL1M"},
    "MEDIUM": {"USA": "TOP2000", "EUR": "TOP1200", "ASI": "MINVOL10M", "GLB": "MINVOL10M"},
    "SMALL": {"USA": "TOP1000", "EUR": "TOP800", "ASI": "TOP500", "GLB": "TOPDIV3000"},
}

#: RAA never runs any other delay.
DELAY = 1

#: Per-region field coverage, used to decide if an expression is RAA-eligible at all.
#: ``REGION_AGNOSTIC_FIELDS`` comes from the region-agnostic catalog sync; entries are
#: ``field -> frozenset(regions)`` where regions are drawn from GLB/USA/EUR/ASI.
_REGIONS = ("GLB", "USA", "EUR", "ASI")


def children_for(expression: str, coverage: dict[str, frozenset[str]]) -> list[str]:
    """Which regions a given expression can actually run in.

    A field with no entry is assumed universal (BRAIN serves it everywhere); a field
    with an entry contributes only its regions. The expression's regions are the
    intersection — the doc's rule: ``abc_usa_asi * xyz_glb_eur`` intersects to nothing.
    """
    if not expression.strip():
        return []
    seen: set[str] = set(_REGIONS)
    for token in _identifiers(expression):
        regions = coverage.get(token)
        if regions is not None:
            seen &= regions
        if not seen:
            break
    return [r for r in _REGIONS if r in seen]


def _identifiers(expression: str) -> list[str]:
    """Field-looking tokens: bare words that are not numeric or operator names."""
    out: list[str] = []
    word = []
    for ch in expression:
        if ch.isalnum() or ch == "_":
            word.append(ch)
        else:
            if word:
                out.append("".join(word))
                word = []
    if word:
        out.append("".join(word))
    return [w for w in out if not w.isdigit()]


def build_request(
    expression: str,
    universe: str,
    *,
    neutralization: str = "NONE",
    decay: int = 0,
    truncation: float = 0.08,
) -> SimulationRequest:
    """One REGION_AGNOSTIC request. ``type`` is derived from ``region`` by the schema."""
    if universe not in UNIVERSES:
        raise ValueError(f"RAA universe must be one of {UNIVERSES}, got {universe!r}")
    settings = SimulationSettings(
        region=REGION_AGNOSTIC_REGION,  # "ALL" — this is what sets the type
        universe=universe,
        delay=DELAY,
        decay=decay,
        neutralization=neutralization,
        truncation=truncation,
    )
    return SimulationRequest(settings=settings, regular=expression)


def plan(
    *,
    expression: str,
    universe: str,
    coverage: dict[str, frozenset[str]],
    neutralization: str = "NONE",
    decay: int = 0,
    truncation: float = 0.08,
) -> dict[str, Any]:
    """What the template screen shows before a simulation is spent: eligibility, the
    per-region universes BRAIN will use, and the child count that drives quota."""
    problems: list[str] = []
    if universe not in UNIVERSES:
        problems.append(f"Unknown RAA universe: {universe}")
    if not expression.strip():
        problems.append("No expression.")
    regions = children_for(expression, coverage)
    if len(regions) < 2:
        problems.append(
            "Region-agnostic simulations must have more than one region: this "
            "expression's fields intersect in "
            + (", ".join(regions) if regions else "no regions")
            + "."
        )
    return {
        "expression": expression,
        "universe": universe,
        "universes": UNIVERSE_MAP.get(universe, {}),
        "delay": DELAY,
        "regions": regions,
        "children": len(regions),
        "problems": problems,
    }
