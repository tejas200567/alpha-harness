"""SuperAlpha research and diversity selection."""

from __future__ import annotations

import math
import re
from collections import Counter
from statistics import median
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from ..brain.schemas import SimulationRequest, SimulationSettings, SimulationType
from ..db.models import SimStatus, StudyStatus, Trial, TrialState
from ..labs import scheduler

if TYPE_CHECKING:
    from ..db.models import Study
    from ..labs.study import Optimizer


PENDING_SEND = "Waiting for cores."

# Two of these -- low_turnover_capacity and low_prod_correlation -- are verified real:
# read live from this account's own 42 existing SuperAlphas (2026-09-22), not guessed.
# The other two are unverified presets kept for now, same caution as everything tonight
# that hasn't been checked against ground truth yet.
SELECTIONS: dict[str, str] = {
    "low_turnover_capacity": "-turnover * (dataset_count >= 1)",
    "low_prod_correlation": (
        "(prod_correlation < 0.40) * long_count / sqrt(universe_size(universe))"
    ),
    "high_sharpe": "sharpe > 1.0",
    "low_ops": "operator_count <= 8",
}

# "decorr" is verified real: the exact combo code found on all 42 of this account's
# existing SuperAlphas, live-checked 2026-09-22 -- not a guess.
COMBOS: dict[str, str] = {
    "equal": "1",
    "decorr": (
        "stats = generate_stats(alpha); innerCorr = self_corr(stats.returns, 500); "
        "ic = if_else(innerCorr == 1.0, nan, innerCorr); "
        "maxCorr = reduce_max(ic); 1 - maxCorr"
    ),
}

DEFAULT_SELECTION_LIMIT = 20
LOCAL_POOL_LIMIT = 250
MIN_CORR_OBS = 60
CORR_PENALTY_START = 0.35

_NUMBER_RE = re.compile(
    r"(?<![A-Za-z_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)
_SPACE_RE = re.compile(r"\s+")


def _structural_fingerprint(expression: str) -> str:
    """
    Build a structural family fingerprint from the FASTEXPR AST.

    Names are normalized to FIELD and numeric literals to CONST.
    Operator/function structure is preserved.
    """

    from ..labs.fastexpr import parse

    tree = parse(expression)

    def normalize(node: Any) -> str:
        kind = getattr(node, "kind", None)
        value = getattr(node, "value", None)
        args = getattr(node, "args", ()) or ()
        # Node.kwargs is a tuple of (key, value) pairs, not a dict -- matches the
        # Node("call", name, args, tuple((k, _literal(v)) for k, v in ...)) shape
        # in labs/template.py's render(). sorted() works directly on the pairs.
        kwargs = getattr(node, "kwargs", ()) or ()

        if kind == "name":
            return "FIELD"

        if kind == "num":
            return "CONST"

        if kind == "binary":
            left = normalize(args[0])
            right = normalize(args[1])
            return f"({left}{value}{right})"

        if kind == "call":
            positional = ",".join(normalize(arg) for arg in args)

            if kwargs:
                keyword_items = ",".join(
                    f"{key}={normalize(val)}"
                    for key, val in sorted(kwargs)
                )
                if positional:
                    return f"{value}({positional},{keyword_items})"
                return f"{value}({keyword_items})"

            return f"{value}({positional})"

        return str(value) if value is not None else str(kind)

    return normalize(tree)

def _pearson(
    left: dict[Any, float],
    right: dict[Any, float],
    *,
    min_obs: int = MIN_CORR_OBS,
) -> float | None:
    common = left.keys() & right.keys()

    if len(common) < min_obs:
        return None

    xs = [float(left[d]) for d in common]
    ys = [float(right[d]) for d in common]

    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)

    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]

    xx = sum(x * x for x in dx)
    yy = sum(y * y for y in dy)

    if xx <= 0.0 or yy <= 0.0:
        return None

    xy = sum(x * y for x, y in zip(dx, dy, strict=True))
    return max(-1.0, min(1.0, xy / math.sqrt(xx * yy)))


def _max_abs_corr(
    alpha_id: str,
    selected: list[str],
    pnl: dict[str, dict[Any, float]],
) -> float:
    if not selected or alpha_id not in pnl:
        return 0.0

    correlations: list[float] = []

    for other in selected:
        if other not in pnl:
            continue

        corr = _pearson(pnl[alpha_id], pnl[other])

        if corr is not None:
            correlations.append(abs(corr))

    return max(correlations, default=0.0)


def _pairwise_corr_stats(
    selected: list[str],
    pnl: dict[str, dict[Any, float]],
) -> tuple[float | None, float | None]:
    values: list[float] = []

    for i, left in enumerate(selected):
        if left not in pnl:
            continue

        for right in selected[i + 1:]:
            if right not in pnl:
                continue

            corr = _pearson(pnl[left], pnl[right])

            if corr is not None:
                values.append(abs(corr))

    if not values:
        return None, None

    return median(values), max(values)


def _quality(candidate: dict[str, Any]) -> float:
    """Local quality score; this never creates a BRAIN simulation."""
    sharpe = float(candidate.get("sharpe") or 0.0)
    fitness = float(candidate.get("fitness") or 0.0)
    turnover = float(candidate.get("turnover") or 0.0)

    sharpe_score = math.tanh(max(-3.0, min(3.0, sharpe)) / 2.0)
    fitness_score = math.tanh(max(-3.0, min(3.0, fitness)) / 2.0)
    turnover_score = 1.0 - min(1.0, max(0.0, turnover))

    return (
        0.55 * sharpe_score
        + 0.30 * fitness_score
        + 0.15 * turnover_score
    )


async def select_diverse_candidates(
    state: Any,
    *,
    region: str,
    delay: int,
    universe: str,
    sharpe_min: float | None = None,
    turnover_max: float | None = None,
    limit: int = DEFAULT_SELECTION_LIMIT,
) -> dict[str, Any]:
    """Select a quality/diversity-balanced local alpha basket."""
    minimum: dict[str, float] = {}
    maximum: dict[str, float] = {}

    if sharpe_min is not None:
        minimum["sharpe"] = sharpe_min

    if turnover_max is not None:
        maximum["turnover"] = turnover_max

    page = await state.alphas.page(
        submitted=True,
        sort_by="sharpe",
        sort_desc=True,
        regions=[region],
        delays=[delay],
        universes=[universe],
        minimum=minimum,
        maximum=maximum,
        search=None,
        limit=LOCAL_POOL_LIMIT,
        offset=0,
    )

    raw = list(page.get("results", []))

    # SUPER should combine only the user's own live REGULAR alphas.
    # Keep this explicit even though submitted=True currently returns only
    # ACTIVE REGULAR rows in the local vault.
    raw = [
        row
        for row in raw
        if str(row.get("status", "")).upper() == "ACTIVE"
        and str(row.get("type", "")).upper() == "REGULAR"
    ]

    candidates: list[dict[str, Any]] = []

    for row in raw:
        expression = row.get("expression")
        family = _structural_fingerprint(expression)

        if not family:
            continue

        candidates.append(
            {
                **row,
                "family": family,
                "_quality": _quality(row),
            }
        )

    by_family: dict[str, list[dict[str, Any]]] = {}

    for candidate in candidates:
        by_family.setdefault(candidate["family"], []).append(candidate)

    for members in by_family.values():
        members.sort(
            key=lambda x: (
                x["_quality"],
                float(x.get("sharpe") or 0.0),
                float(x.get("fitness") or 0.0),
            ),
            reverse=True,
        )

    representatives = [
        members[0]
        for members in by_family.values()
    ]

    representatives.sort(
        key=lambda x: x["_quality"],
        reverse=True,
    )

    pnl_ids = [
        str(row["alphaId"])
        for row in representatives
        if row.get("hasPnl")
    ]

    pnl = await state.alphas.daily_pnl(pnl_ids)

    selected: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    selected_families: set[str] = set()

    remaining = list(representatives)

    while remaining and len(selected) < limit:
        best: dict[str, Any] | None = None
        best_score = -float("inf")

        for candidate in remaining:
            alpha_id = str(candidate["alphaId"])
            family = str(candidate["family"])

            max_corr = _max_abs_corr(
                alpha_id,
                selected_ids,
                pnl,
            )

            novelty = (
                1.0
                if family not in selected_families
                else 0.0
            )

            score = (
                0.60 * float(candidate["_quality"])
                + 0.20 * novelty
                - 0.20 * max_corr
            )

            if selected_ids and alpha_id not in pnl:
                score -= 0.10

            if score > best_score:
                best_score = score
                best = candidate

        if best is None:
            break

        remaining.remove(best)

        item = dict(best)
        item["maxCorrToSelected"] = _max_abs_corr(
            str(item["alphaId"]),
            selected_ids,
            pnl,
        )

        selected.append(item)

        selected_ids.append(str(item["alphaId"]))
        selected_families.add(str(item["family"]))

    # Fill remaining slots with additional family members only when useful.
    if len(selected) < limit:
        extras = [
            member
            for members in by_family.values()
            for member in members[1:]
        ]

        while extras and len(selected) < limit:
            best: dict[str, Any] | None = None
            best_score = -float("inf")

            for candidate in extras:
                alpha_id = str(candidate["alphaId"])

                max_corr = _max_abs_corr(
                    alpha_id,
                    selected_ids,
                    pnl,
                )

                score = (
                    0.70 * float(candidate["_quality"])
                    - 0.30 * max_corr
                )

                if max_corr > CORR_PENALTY_START:
                    score -= 0.25 * (
                        (max_corr - CORR_PENALTY_START)
                        / (1.0 - CORR_PENALTY_START)
                    )

                if score > best_score:
                    best_score = score
                    best = candidate

            if best is None:
                break

            extras.remove(best)

            item = dict(best)
            item["maxCorrToSelected"] = _max_abs_corr(
                str(item["alphaId"]),
                selected_ids,
                pnl,
            )

            selected.append(item)
            selected_ids.append(str(item["alphaId"]))

    median_corr, max_corr = _pairwise_corr_stats(
        selected_ids,
        pnl,
    )

    family_counts = Counter(
        str(x["family"])
        for x in candidates
    )

    return {
        "eligible_count": int(page.get("total", 0)),
        "pool_count": len(raw),
        "family_count": len(by_family),
        "structural_redundancy_removed": max(
            0,
            len(candidates) - len(representatives),
        ),
        "selected_count": len(selected),
        "selected_family_count": len(selected_families),
        "median_pair_corr": median_corr,
        "max_pair_corr": max_corr,
        "selected": [
            {
                "alphaId": str(row["alphaId"]),
                "expression": row.get("expression"),
                "family": row.get("family"),
                "familySize": family_counts.get(
                    str(row["family"]),
                    1,
                ),
                "sharpe": row.get("sharpe"),
                "fitness": row.get("fitness"),
                "turnover": row.get("turnover"),
                "operatorCount": row.get("operatorCount"),
                "hasPnl": bool(row.get("hasPnl")),
                "maxCorrToSelected": row.get(
                    "maxCorrToSelected"
                ),
            }
            for row in selected
        ],
    }


def build_request(
    *,
    region: str,
    delay: int,
    universe: str,
    neutralization: str,
    decay: int,
    truncation: float,
    selection: str,
    combo: str,
) -> SimulationRequest:
    """Build one SUPER simulation request."""
    return SimulationRequest(
        type=SimulationType.SUPER,
        settings=SimulationSettings(
            region=region,
            delay=delay,
            universe=universe,
            neutralization=neutralization,
            decay=decay,
            truncation=truncation,
        ),
        selection=selection,
        combo=combo,
    )


def seed_trials(request: SimulationRequest) -> Any:
    """Park the single SUPER trial until a core is available."""

    def build(study_id: int) -> list[Trial]:
        return [
            Trial(
                study_id=study_id,
                number=0,
                params={"selection": request.selection},
                distributions={},
                expression=request.combo,
                settings=request.settings.model_dump(
                    by_alias=True,
                    exclude_none=True,
                ),
                state=TrialState.PRUNED,
                message=PENDING_SEND,
            )
        ]

    return build


async def refill(
    optimizer: Optimizer,
    row: Study,
    want: int,
    waiting: bool,
) -> int:
    """Send the parked SUPER simulation when a core is available."""
    parked = (
        Trial.study_id == row.id,
        Trial.state == TrialState.PRUNED,
        Trial.message == PENDING_SEND,
    )

    async with optimizer.db.session() as session:
        batch = (
            (
                await session.scalars(
                    select(Trial).where(*parked).limit(want)
                )
            ).all()
            if want > 0
            else []
        )

        sent = await _send(
            optimizer,
            row,
            batch,
        ) if batch else 0

        left = await session.scalar(
            select(Trial.id).where(*parked).limit(1)
        )

    if not (waiting or sent or left):
        await scheduler.finish(
            optimizer,
            row.id,
            StudyStatus.COMPLETE,
            "",
        )

    return sent


async def _send(
    optimizer: Optimizer,
    row: Study,
    batch: Any,
) -> int:
    requests = [
        SimulationRequest(
            type=SimulationType.SUPER,
            settings=SimulationSettings.model_validate(
                trial.settings
            ),
            selection=trial.params.get("selection"),
            combo=trial.expression,
        )
        for trial in batch
    ]

    outcomes = (
        await optimizer.engine.enqueue(
            requests,
            task=row.task,
            skip_duplicates=True,
        )
    ).get("outcomes", [])

    for index, trial in enumerate(batch):
        outcome = (
            outcomes[index]
            if index < len(outcomes)
            else {}
        )

        trial.state = TrialState.QUEUED
        trial.simulation_record_id = outcome.get(
            "recordId"
        )
        trial.alpha_id = outcome.get("alphaId")
        trial.message = (
            scheduler.FREE
            if outcome.get("status")
            == str(SimStatus.SKIPPED)
            else None
        )

    return len(batch)
