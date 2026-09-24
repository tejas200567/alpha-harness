"""Data Explorer: syncing the catalog and querying it."""

from __future__ import annotations

import re as _re
from collections import defaultdict
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from ..brain.filters import AlphaQuery, Filter
from ..brain.schemas import REGION_AGNOSTIC_REGION, SimulationRequest, SimulationSettings
from ..brain.settings_schema import valid_values
from ..catalog.description_rules import build_expression, is_metadata_field
from ..catalog.field_intelligence import field_intelligence
from ..catalog.pyramids import pyramid_grid
from ..catalog.queries import FieldFilter, Tuple4
from ..catalog.sync import SyncTarget
from ..db.models import utcnow
from ..engine.packer import MAX_BATCH
from ..labs.fastexpr import ParseError, data_fields, parse
from ..labs.launch import AddedTask, add_study
from ..labs.params import DESC_AWARE_SAMPLER, DescAwareParams
from ..schemas import Out, SyncAllRun
from ..tools import settings_sampler
from ..vault.store import SUBMITTED
from .alphas import AlphaStats, degenerate_warning
from .deps import State, refuse

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def scope(
    region: Annotated[str, Query(description="e.g. USA, EUR, GLB")],
    delay: Annotated[int, Query(ge=0, le=1)],
    universe: Annotated[str, Query(description="e.g. TOP3000")],
    instrument_type: Annotated[str, Query(alias="instrumentType")] = "EQUITY",
) -> Tuple4:
    """The (instrumentType, region, delay, universe) scope every query needs."""
    return Tuple4(instrument_type=instrument_type, region=region, delay=delay, universe=universe)


Scope = Annotated[Tuple4, Depends(scope)]


# --- wire shapes: DuckDB rows keep their snake_case column names ------------


class Market(Out):
    instrument_type: str
    region: str
    delay: int
    universe: str


class Cancelled(Out):
    cancelled: bool


class PyramidColumn(Out):
    region: str
    delay: int


class PyramidCategory(Out):
    id: str
    name: str


class PyramidCell(Out):
    category_id: str
    region: str
    delay: int
    multiplier: float | None
    alpha_count: int
    #: 3+ alphas this quarter.
    lit: bool
    synced: bool


class Quarter(Out):
    """Calendar quarter in platform time; ``end`` is the next quarter's first day."""

    start: str
    end: str
    today: str


class PyramidGrid(Out):
    columns: list[PyramidColumn]
    categories: list[PyramidCategory]
    cells: list[PyramidCell]
    quarter: Quarter
    #: Submitted Alphas a pyramid needs before BRAIN counts it as formulated.
    alphas_per_pyramid: int


class CatalogScopeRow(BaseModel):
    instrument_type: str
    region: str
    delay: int
    universe: str
    fields: int
    synced_at: datetime | None


class CatalogCounts(BaseModel):
    fields: int
    datasets: int
    categories: int
    subcategories: int


class CatalogSize(BaseModel):
    """What the catalog's data occupies, which is smaller than its file."""

    used_bytes: int


class CatalogStats(BaseModel):
    coverage_min: float | None = None
    coverage_max: float | None = None
    coverage_median: float | None = None
    alpha_count_max: int | None = None
    user_count_max: int | None = None
    pyramid_multiplier_max: float | None = None


class DataFieldRow(BaseModel):
    field_id: str
    dataset_id: str | None
    category_id: str | None
    category_name: str | None
    subcategory_id: str | None
    subcategory_name: str | None
    description: str | None
    field_type: str | None
    #: BRAIN's "Instrument Coverage": the share of the universe the field has a value for.
    coverage: float | None
    #: BRAIN's "Date Coverage": the share of the history it has a value for. A field can be
    #: complete on one and threadbare on the other, so neither stands in for the other.
    date_coverage: float | None
    user_count: int | None
    alpha_count: int | None
    pyramid_multiplier: float | None
    #: JSON array text.
    themes: str | None
    #: BRAIN's "Date added": when the field first appeared in this market. Null until the
    #: market is downloaded again, because it was not stored before.
    date_created: date | None


class DataFieldDetail(DataFieldRow):
    instrument_type: str
    region: str
    delay: int
    universe: str
    synced_at: datetime | None


class FieldPage(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[DataFieldRow]


class CategoryFacet(BaseModel):
    id: str
    name: str | None
    n: int


class SubcategoryFacet(CategoryFacet):
    category_id: str | None


class DatasetFacet(BaseModel):
    id: str
    category_id: str | None
    subcategory_id: str | None
    n: int


class TypeFacet(BaseModel):
    id: str
    n: int


class CatalogFacets(BaseModel):
    categories: list[CategoryFacet]
    subcategories: list[SubcategoryFacet]
    datasets: list[DatasetFacet]
    types: list[TypeFacet]


class FieldAvailabilityRow(BaseModel):
    instrument_type: str
    region: str
    delay: int
    universe: str
    coverage: float | None
    alpha_count: int | None
    field_type: str | None


class DatasetRow(BaseModel):
    dataset_id: str
    name: str | None
    description: str | None
    category_id: str | None
    category_name: str | None
    subcategory_id: str | None
    subcategory_name: str | None
    coverage: float | None
    value_score: float | None
    user_count: int | None
    alpha_count: int | None
    field_count: int | None
    pyramid_multiplier: float | None


# --- syncing --------------------------------------------------------------


async def _markets(state: State) -> list[SyncTarget]:
    """Every EQUITY market the account can simulate, from BRAIN's own settings schema.

    A new region or universe is picked up without a code change. Region ``ALL`` is in here
    like any other: it is drawn in the sync matrix so an account that can run region-agnostic
    alphas can see whether it holds them. What it is *not* is part of a sync by default —
    see :func:`start_sync_all`.
    """
    schema = (
        await state.metadata.cached_settings_schema() or await state.metadata.refresh_metadata()
    )
    # EQUITY only, the one instrument type the Data Explorer offers.
    base: dict[str, Any] = {"instrumentType": "EQUITY"}
    return [
        SyncTarget(instrument_type="EQUITY", region=region, delay=int(delay), universe=universe)
        for region in valid_values(schema, "region", base)
        for delay in valid_values(schema, "delay", {**base, "region": region})
        for universe in valid_values(schema, "universe", {**base, "region": region, "delay": delay})
    ]


@router.get("/markets")
async def markets(state: State) -> list[Market]:
    """Every market BRAIN offers: what the sync matrix draws."""
    return [
        Market(
            instrument_type=t.instrument_type, region=t.region, delay=t.delay, universe=t.universe
        )
        for t in await _markets(state)
    ]


@router.post("/sync-all")
async def start_sync_all(state: State) -> SyncAllRun:
    """Download every ordinary market: all fields first, then dataset details.

    Region ``ALL`` is not one of them; it has :func:`start_sync_region_agnostic` to itself.

    Runs in the background; progress, including each market's state, arrives over the
    WebSocket ``sync`` topic.
    """
    targets = [t for t in await _markets(state) if t.region != REGION_AGNOSTIC_REGION]
    if not targets:
        raise refuse(
            503,
            "no_markets",
            "BRAIN's settings list no markets to download. Sign in again and retry.",
        )
    return SyncAllRun.model_validate(await state.sync.start_all(targets))


@router.post("/sync-region-agnostic")
async def start_sync_region_agnostic(state: State) -> SyncAllRun:
    """Download the region-agnostic market: every universe of region ``ALL``.

    Its own route because it is its own download. BRAIN serves this market only fifty fields
    at a time, so it is read dataset by dataset — about ten minutes per universe where an
    ordinary market is seconds — and only an account running region-agnostic alphas needs it.
    """
    targets = [t for t in await _markets(state) if t.region == REGION_AGNOSTIC_REGION]
    if not targets:
        raise refuse(
            403,
            "no_region_agnostic",
            "This account cannot run region-agnostic simulations, so BRAIN offers no "
            "all-regions market to download.",
        )
    return SyncAllRun.model_validate(await state.sync.start_all(targets))


@router.post("/sync/runs/{run_id}/cancel")
async def cancel_run(run_id: int, state: State) -> Cancelled:
    return Cancelled(cancelled=await state.sync.cancel(run_id))


@router.get("/pyramids")
async def pyramids(state: State) -> PyramidGrid:
    """Every pyramid: its multiplier, this quarter's alpha count, and download state."""
    return PyramidGrid.model_validate(await pyramid_grid(state.endpoints, state.catalog))


@router.get("/scopes")
async def scopes(state: State) -> list[CatalogScopeRow]:
    """Which scopes hold data locally, and how much."""
    return [CatalogScopeRow.model_validate(r) for r in await state.queries.synced_tuples()]


# --- reading --------------------------------------------------------------


@router.get("/counts")
async def counts(scope: Scope, state: State) -> CatalogCounts:
    """Datasets / categories / subcategories / fields for one scope."""
    return CatalogCounts.model_validate(await state.queries.counts(scope))


@router.get("/size")
async def size(state: State) -> CatalogSize:
    """How much the catalog's data actually takes up."""
    return CatalogSize(used_bytes=await state.catalog.used_bytes())


@router.get("/stats")
async def stats(scope: Scope, state: State) -> CatalogStats:
    """Value ranges, so filter controls can bound themselves to real data."""
    return CatalogStats.model_validate(await state.queries.stats(scope))


#: Module-level singleton so the default is not rebuilt per request.
DEFAULT_FIELD_FILTER = FieldFilter()


@router.post("/fields")
async def fields(
    scope: Scope,
    state: State,
    filters: Annotated[FieldFilter, Body()] = DEFAULT_FIELD_FILTER,
) -> FieldPage:
    """Filtered, sorted, paginated data fields.

    POST rather than GET because the filter set is large and structured; the operation
    is still a pure read.
    """
    return FieldPage.model_validate(await state.queries.fields(scope, filters))


@router.post("/facets")
async def facets(
    scope: Scope,
    state: State,
    filters: Annotated[FieldFilter, Body()] = DEFAULT_FIELD_FILTER,
) -> CatalogFacets:
    """Categories / subcategories / datasets / types with counts under the other filters."""
    return CatalogFacets.model_validate(await state.queries.facets(scope, filters))


class DescAwareCandidate(Out):
    field_id: str
    description: str
    classification: str
    template_used: str
    expression: str


class DescAwareSweepResult(Out):
    candidates: list[DescAwareCandidate]
    excluded_metadata_count: int
    total_fields: int


class CategoryPoolCoverage(Out):
    category_id: str
    category_name: str | None
    #: Real fields available in the catalog for this category, in this market.
    catalog_fields: int
    #: Distinct fields from this category actually used across the unsubmitted pool.
    pool_fields: int
    #: Unsubmitted Alphas using at least one field from this category (an Alpha using
    #: several fields from one category counts once per field, so this can exceed the
    #: pool -- a rough weight, not a distinct count).
    pool_alphas: int
    catalog_share: float
    pool_share: float
    #: catalog_share - pool_share. Positive means the category has more real opportunity
    #: than its current share of the pool reflects -- genuinely under-mined relative to
    #: its own size, not just small in absolute terms.
    gap: float
    #: This category's real BRAIN pyramid multiplier at this exact region/delay, from
    #: /api/catalog/pyramids. None when BRAIN offers no pyramid here at all.
    pyramid_multiplier: float | None
    #: Alphas submitted in this pyramid this quarter (BRAIN's own count, not the harness's).
    pyramid_alpha_count: int | None
    #: Whether this pyramid already has >=3 this quarter, per Genius rules.
    pyramid_lit: bool | None
    #: gap * pyramid_multiplier when both are known, gap alone otherwise. Ranks a category
    #: an unlit, high-multiplier pyramid needs above one that is already lit or low-value,
    #: even at an identical coverage gap.
    opportunity: float


class PoolCoverageResult(Out):
    categories: list[CategoryPoolCoverage]
    pool_size: int
    unreadable: int


@router.get("/pool-coverage")
async def pool_coverage(scope: Scope, state: State) -> PoolCoverageResult:
    """Where the unsubmitted pool is genuinely under-mined, relative to real catalog size.

    Phase 1 of the diversity pipeline: a coverage-gap calculation, not a hardcoded term
    list. catalog_share - pool_share avoids the naive "small category = explore it"
    mistake -- a tiny category isn't a gap unless the pool represents it even less than
    its own small size would suggest.
    """
    catalog_rows = await state.catalog.query(
        "SELECT category_id, category_name, count(*) AS n FROM data_field "
        "WHERE instrument_type = ? AND region = ? AND delay = ? AND universe = ? "
        "AND category_id IS NOT NULL GROUP BY category_id, category_name",
        [scope.instrument_type, scope.region, scope.delay, scope.universe],
    )
    total_catalog = sum(int(r["n"]) for r in catalog_rows)

    pool_rows = await state.catalog.query(
        f"""
        SELECT a.expression FROM alpha a
        WHERE coalesce(a.instrument_type, 'EQUITY') = ?
          AND a.region = ? AND a.delay = ? AND a.universe = ?
          AND NOT {SUBMITTED} AND a.expression IS NOT NULL
        """,  # noqa: S608
        [scope.instrument_type, scope.region, scope.delay, scope.universe],
    )
    pool_size = len(pool_rows)

    unreadable = 0
    field_alpha_count: dict[str, int] = defaultdict(int)
    for row in pool_rows:
        try:
            tree = parse(row["expression"] or "")
        except ParseError:
            unreadable += 1
            continue
        for field_id in set(data_fields(tree)):
            field_alpha_count[field_id] += 1

    used_fields = list(field_alpha_count)
    field_category: dict[str, str] = {}
    if used_fields:
        placeholders = ",".join("?" for _ in used_fields)
        rows = await state.catalog.query(
            f"SELECT field_id, category_id FROM data_field WHERE field_id IN ({placeholders})",  # noqa: S608
            used_fields,
        )
        field_category = {
            str(r["field_id"]): str(r["category_id"]) for r in rows if r.get("category_id")
        }

    pool_fields_by_category: dict[str, set[str]] = defaultdict(set)
    pool_alphas_by_category: dict[str, int] = defaultdict(int)
    for field_id, count in field_alpha_count.items():
        category = field_category.get(field_id)
        if category:
            pool_fields_by_category[category].add(field_id)
            pool_alphas_by_category[category] += count

    total_pool_fields_used = len(used_fields)
    grid = await pyramid_grid(state.endpoints, state.catalog)
    pyramid_by_key = {
        (cell["categoryId"], cell["region"], int(cell["delay"])): cell
        for cell in grid["cells"]
    }

    categories = [
        CategoryPoolCoverage(
            category_id=str(row["category_id"]),
            category_name=row.get("category_name"),
            catalog_fields=int(row["n"]),
            pool_fields=len(pool_fields_by_category.get(str(row["category_id"]), set())),
            pool_alphas=pool_alphas_by_category.get(str(row["category_id"]), 0),
            catalog_share=(int(row["n"]) / total_catalog) if total_catalog else 0.0,
            pool_share=(
                len(pool_fields_by_category.get(str(row["category_id"]), set()))
                / total_pool_fields_used
            )
            if total_pool_fields_used
            else 0.0,
            gap=0.0,
            pyramid_multiplier=None,
            pyramid_alpha_count=None,
            pyramid_lit=None,
            opportunity=0.0,
        )
        for row in catalog_rows
    ]
    for c in categories:
        c.gap = c.catalog_share - c.pool_share
        cell = pyramid_by_key.get((c.category_id, scope.region, scope.delay))
        if cell is not None:
            c.pyramid_multiplier = cell.get("multiplier")
            c.pyramid_alpha_count = cell.get("alphaCount")
            c.pyramid_lit = cell.get("lit")
        # An unlit pyramid needing few more Alphas to hit 3 is worth more than its gap
        # alone says -- 1.5x on top of the multiplier for it, so a positive-gap category
        # close to lighting a high-multiplier pyramid ranks above an already-lit one at
        # the same gap.
        unlit_with_progress = (
            c.pyramid_lit is False
            and c.pyramid_alpha_count is not None
            and c.pyramid_alpha_count > 0
        )
        near_light_bonus = 1.5 if unlit_with_progress else 1.0
        c.opportunity = (
            c.gap * c.pyramid_multiplier * near_light_bonus
            if c.pyramid_multiplier is not None
            else c.gap
        )
    categories.sort(key=lambda c: -c.opportunity)

    return PoolCoverageResult(categories=categories, pool_size=pool_size, unreadable=unreadable)


class HighImpactCandidate(DescAwareCandidate):
    category_id: str
    category_name: str | None
    #: This category's opportunity score at the time of the sweep (see pool_coverage).
    opportunity: float


class HighImpactBatchResult(Out):
    candidates: list[HighImpactCandidate]
    #: The categories actually swept, ranked, for context on why these and not others.
    categories_used: list[CategoryPoolCoverage]
    pool_size: int


@router.get("/high-impact-batch")
async def high_impact_batch(
    scope: Scope,
    state: State,
    top_n: int = 6,
    per_category_limit: int = 20,
) -> HighImpactBatchResult:
    """The whole opportunity pipeline in one call: coverage gap x pyramid multiplier,
    ranked, swept by real category_id for the top opportunities, ready for
    /description-aware-sweep/task. A preview -- nothing is simulated here.
    """
    coverage = await pool_coverage(scope, state)
    top = [c for c in coverage.categories if c.opportunity > 0][:top_n]

    candidates: list[HighImpactCandidate] = []
    for c in top:
        result = await description_aware_sweep(
            scope,
            state,
            FieldFilter(
                category_ids=[c.category_id],
                sort_by="alpha_count",
                sort_desc=False,
                limit=per_category_limit,
            ),
        )
        candidates.extend(
            HighImpactCandidate(
                field_id=cand.field_id,
                description=cand.description,
                classification=cand.classification,
                template_used=cand.template_used,
                expression=cand.expression,
                category_id=c.category_id,
                category_name=c.category_name,
                opportunity=c.opportunity,
            )
            for cand in result.candidates
        )

    return HighImpactBatchResult(
        candidates=candidates, categories_used=top, pool_size=coverage.pool_size
    )


_STOPWORDS = frozenset({
    "a", "an", "the", "of", "for", "in", "on", "to", "and", "or", "is", "are",
    "this", "that", "with", "as", "by", "from", "its", "at", "be", "vs", "per",
})

#: Universal auxiliary fields nearly every template reads (as a denominator, a size
#: weight, or a scaling factor) -- never the actual signal on their own. Found live:
#: an alpha's data_fields() sorts alphabetically, so an expression using both "cap"
#: and a real signal field picked "cap" purely because it sorts first -- an
#: infrastructure input, not the proven pattern.
_AUXILIARY_FIELDS = frozenset({
    "cap", "close", "open", "high", "low", "volume", "returns", "vwap",
    "adv20", "sharesout", "dividend", "split",
})


def _tokenize(text: str) -> set[str]:
    words = _re.findall(r"[a-z]+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


class ProvenPatternCandidate(Out):
    proven_alpha_id: str
    proven_field_id: str
    proven_fitness: float | None
    proven_expression: str
    matched_field_id: str
    matched_field_description: str | None
    #: Jaccard similarity between the two fields' description text, 0-1.
    similarity: float
    #: The proven expression with proven_field_id replaced by matched_field_id --
    #: the same construction, cloned onto an unused but similarly-described field.
    new_expression: str


class ProvenPatternBatchResult(Out):
    candidates: list[ProvenPatternCandidate]
    proven_alphas_examined: int
    pool_size: int


@router.get("/proven-pattern-batch")
async def proven_pattern_batch(
    scope: Scope,
    state: State,
    min_fitness: float = 1.5,
    similarity_threshold: float = 0.25,
    top_n: int = 10,
    max_proven: int = 30,
) -> ProvenPatternBatchResult:
    """Clone real, already-proven Alpha constructions onto unused fields whose real
    description overlaps meaningfully with the proven field's -- pattern cloning from
    evidence, not template classification. Different from description-aware-sweep:
    that routes a field to one of 13 fixed shapes by keyword; this instead takes an
    Alpha that already scored well, finds the field it's built on, and looks for other
    fields -- in the same category, never already used in this pool -- whose own
    description reads similarly, then reuses the exact proven expression on them.
    """
    query = AlphaQuery(
        limit=100,
        filters=[
            Filter(field="settings.region", op="=", value=scope.region),
            Filter(field="settings.delay", op="=", value=scope.delay),
            Filter(field="settings.universe", op="=", value=scope.universe),
            Filter(field="is.fitness", op=">=", value=min_fitness),
        ],
    )
    page = await state.endpoints.list_alphas(query)
    def _clean(a: dict[str, Any]) -> bool:
        isd = a.get("is") or {}
        if isd.get("fitness") is None:
            return False
        return degenerate_warning(AlphaStats.model_validate(isd)) is None

    proven_rows = sorted(
        (a for a in (page.get("results") or []) if _clean(a)),
        key=lambda a: -(a["is"]["fitness"]),
    )[:max_proven]

    pool_rows = await state.catalog.query(
        f"""
        SELECT a.expression FROM alpha a
        WHERE coalesce(a.instrument_type, 'EQUITY') = ?
          AND a.region = ? AND a.delay = ? AND a.universe = ?
          AND NOT {SUBMITTED} AND a.expression IS NOT NULL
        """,  # noqa: S608
        [scope.instrument_type, scope.region, scope.delay, scope.universe],
    )
    used_fields: set[str] = set()
    for row in pool_rows:
        try:
            tree = parse(row["expression"] or "")
        except ParseError:
            continue
        used_fields.update(data_fields(tree))

    catalog_rows = await state.catalog.query(
        "SELECT field_id, description, category_id FROM data_field "
        "WHERE instrument_type = ? AND region = ? AND delay = ? AND universe = ?",
        [scope.instrument_type, scope.region, scope.delay, scope.universe],
    )
    desc_by_field = {r["field_id"]: r.get("description") or "" for r in catalog_rows}
    category_by_field = {r["field_id"]: r.get("category_id") for r in catalog_rows}
    by_category: dict[str | None, list[str]] = {}
    for r in catalog_rows:
        by_category.setdefault(r.get("category_id"), []).append(r["field_id"])

    candidates: list[ProvenPatternCandidate] = []
    for a in proven_rows:
        if len(candidates) >= top_n:
            break
        regular = a.get("regular")
        code = regular.get("code") if isinstance(regular, dict) else regular
        if not code:
            continue
        try:
            tree = parse(code)
        except ParseError:
            continue
        fields = [f for f in data_fields(tree) if f not in _AUXILIARY_FIELDS]
        if not fields:
            continue
        proven_field = fields[0]
        proven_desc = desc_by_field.get(proven_field)
        if not proven_desc:
            continue
        proven_tokens = _tokenize(proven_desc)
        category = category_by_field.get(proven_field)
        pool_candidates = by_category.get(category, [])
        scored = sorted(
            (
                (_jaccard(proven_tokens, _tokenize(desc_by_field.get(fid, ""))), fid)
                for fid in pool_candidates
                if fid != proven_field and fid not in used_fields
            ),
            key=lambda x: -x[0],
        )
        for sim, fid in scored[:3]:
            if sim < similarity_threshold:
                break
            new_expr = _re.sub(rf"\b{_re.escape(proven_field)}\b", fid, code)
            candidates.append(
                ProvenPatternCandidate(
                    proven_alpha_id=str(a.get("id")),
                    proven_field_id=proven_field,
                    proven_fitness=(a.get("is") or {}).get("fitness"),
                    proven_expression=code,
                    matched_field_id=fid,
                    matched_field_description=desc_by_field.get(fid),
                    similarity=round(sim, 4),
                    new_expression=new_expr,
                )
            )
            if len(candidates) >= top_n:
                break

    return ProvenPatternBatchResult(
        candidates=candidates,
        proven_alphas_examined=len(proven_rows),
        pool_size=len(pool_rows),
    )


@router.post("/description-aware-sweep")
async def description_aware_sweep(
    scope: Scope,
    state: State,
    filters: Annotated[FieldFilter, Body()] = DEFAULT_FIELD_FILTER,
) -> DescAwareSweepResult:
    """Classify each field by its real description, route it to the expression
    shape suited to what it represents, instead of sweeping one tree uniformly
    across every field."""
    page = await state.queries.fields(scope, filters)
    candidates = []
    excluded = 0
    for f in page["results"]:
        desc = f.get("description") or ""
        if is_metadata_field(desc):
            excluded += 1
            continue
        expr, reason, template_used = build_expression(f["field_id"], desc, f.get("field_type", "MATRIX"))
        candidates.append(DescAwareCandidate(
            field_id=f["field_id"], description=desc,
            classification=reason, template_used=template_used, expression=expr,
        ))
    return DescAwareSweepResult(
        candidates=candidates, excluded_metadata_count=excluded, total_fields=page["total"],
    )


class FieldPerformanceRecord(Out):
    scope: str
    n: int
    mean_sharpe: float | None
    mean_fitness: float | None


class NeutralizationSignal(Out):
    neutralization: str
    n: int
    mean_sharpe: float | None
    mean_fitness: float | None


class FieldIntelligence(Out):
    performance: list[FieldPerformanceRecord]
    neutralization_works: list[NeutralizationSignal]
    neutralization_fails: list[NeutralizationSignal]


@router.get("/fields/{field_id}/intelligence")
async def field_intelligence_route(field_id: str) -> FieldIntelligence:
    """Real evidence for one field from the community/paper knowledge graph:
    Sharpe/fitness history by scope (PERFORMS_IN), and which neutralizations
    have historically worked or failed for it. Independent of the account's
    own catalog sync -- this is external, aggregated community evidence."""
    return FieldIntelligence.model_validate(field_intelligence(field_id))


class DescAwareCandidateInput(BaseModel):
    field_id: str
    expression: str


class DescAwareTaskRequest(BaseModel):
    candidates: list[DescAwareCandidateInput]
    decay: int = 6
    truncation: float = 0.08
    neutralization: str = "NONE"
    cores: int = 4


@router.post("/description-aware-sweep/task", status_code=201)
async def description_aware_sweep_task(
    scope: Scope, body: DescAwareTaskRequest, state: State
) -> AddedTask:
    """Run every candidate from a description-aware sweep as a real, fixed-list task.

    Reuses Settings Sampler's seed_trials/refill machinery as-is: both already implement
    "every simulation is written up front, so nothing is sampled" -- exactly this shape,
    just for pre-classified fields instead of one alpha across markets.
    """
    if not body.candidates:
        raise refuse(422, "no_candidates", "No candidates to run.")
    if body.cores > state.engine.slots:
        raise refuse(
            422, "too_many_cores",
            f"The engine has {state.engine.slots} slots, so a task cannot hold {body.cores}.",
        )

    requests = [
        SimulationRequest(
            settings=SimulationSettings(
                region=scope.region, universe=scope.universe, delay=scope.delay,
                neutralization=body.neutralization, decay=body.decay, truncation=body.truncation,
                max_trade="OFF", max_position="OFF",
            ),
            regular=c.expression,
        )
        for c in body.candidates
    ]
    row = await add_study(
        state,
        now=utcnow(),
        lab="Description-Aware Sweep",
        prefix="descaware",
        sampler=DESC_AWARE_SAMPLER,
        params=DescAwareParams(
            region=scope.region, delay=scope.delay,
            candidate_count=len(requests), cores=body.cores,
        ),
        objective="sharpe",
        simulations=len(requests),
        batch_size=(body.cores + 1) * MAX_BATCH,
        template_source="description-aware-sweep",
        template_name=f"Description-Aware Sweep · {scope.region}/{scope.universe}",
        seeds=settings_sampler.seed_trials(requests),
    )
    return AddedTask(id=row.id, name=row.name)


@router.get("/fields/{field_id}")
async def field_detail(field_id: str, scope: Scope, state: State) -> DataFieldDetail:
    row = await state.queries.field(scope, field_id)
    if row is None:
        raise HTTPException(404, f"{field_id} is not in the catalog for {scope.label}")
    return DataFieldDetail.model_validate(row)


@router.get("/fields/{field_id}/availability")
async def field_availability(field_id: str, state: State) -> list[FieldAvailabilityRow]:
    """Every scope this field exists in.

    Not every field is available in every region/delay/universe, so this is the check
    that stops a template being expanded into simulations that cannot run.
    """
    return [
        FieldAvailabilityRow.model_validate(r)
        for r in await state.queries.field_availability(field_id)
    ]


@router.get("/datasets")
async def datasets(scope: Scope, state: State) -> list[DatasetRow]:
    return [DatasetRow.model_validate(r) for r in await state.queries.datasets(scope)]
