"""
Description-aware template selection.

Classifies a field by its real description text, then routes it to the
EXISTING Template Lab template best suited to that classification and
renders a real expression from that template's actual tree via
labs.template.render() -- not a separate hardcoded string.
"""
import re

from ..labs.template import render

METADATA_EXCLUSION_PATTERNS = re.compile(
    r"\btimestamp\b|\bunix epoch\b|\bunique identifier\b|\bstart time\b|\bend time\b"
    r"|\bcurrency code\b|\biso 4217\b|\bisexcluded\b|\bprevalue\b|\breceivetime\b"
    r"|\bage of\b.*\bestimates? in days\b|\bdictionary of\b|\breporting period\b"
    r"|\bevent start time\b|\bingestion\b|\btext_full\b|\bdisplay label\b"
    r"|lastupdated|\blast.updated\b|\bin gmt\b|\bin utc\b|\bnarrative\b",
    re.IGNORECASE,
)

CLASSIFICATION_RULES = [
    (r"\bsurprise\b", "earnings-surprise-type"),
    (r"\bpredicted\b|\bforecast\b|smart.?estimates?|\bconsensus\b", "analyst-estimate-type"),
    (r"\bchange\b|\bdelta\b|\bgrowth\b|\brevision\b", "change-type"),
    (r"\bratio\b|\bpercent(age)?\b|\bpct\b|\bproportion\b", "ratio-type"),
    (r"\bcount\b|\bnumber\b|\bnum\b", "count-type"),
    (r"\bscore\b|\bindex\b|\brating\b|\brank\b", "score-type"),
    (r"\bvolatility\b|\bvariance\b|\bstd\b|\bstandard deviation\b|\brisk\b|\bstability\b|\bvariability\b", "risk-type"),
    (r"\byield\b|\bvalue\b|\bmultiple\b|\bexpected return\b|\brate of return\b", "valuation-type"),
    (r"\bmomentum\b|\btrend\b|\bacceleration\b", "momentum-type"),
    (r"\bsentiment\b|\btone\b|\bbuzz\b|\bpositive signal\b|\bnegative signal\b", "sentiment-type"),
    (r"\bprice\b|\b52.?week\b|\bhigh\b|\blow\b", "price-type"),
    (r"\bnet\b|\btotal\b|\baggregat|\bassets\b|\bdebt\b|\bequity\b|\bexpense\b|\bincome\b"
     r"|\brevenue\b|\bcash flow\b|\bimpairment\b|\bwrite.?down\b|\bwrite.?off\b"
     r"|\binterest\b|\bsum\b|\breduction\b|\bffo\b|\bminority\b|\beps\b|\bearnings per share\b", "level-fundamental-type"),
    (r"\bdeviation\b|\berror\b|\bmad\b|\bmae\b", "diagnostic-type"),
]
DEFAULT_REASON = "default"


def is_metadata_field(description: str) -> bool:
    return bool(METADATA_EXCLUSION_PATTERNS.search(description or ""))


def classify(description: str) -> str:
    desc_l = (description or "").lower()
    for pattern, reason in CLASSIFICATION_RULES:
        if re.search(pattern, desc_l):
            return reason
    return DEFAULT_REASON


_CLEAN_THEN_SCORE = {"version": 1, "root": {
    "kind": "op", "ops": ["group_rank"], "args": [
        {"kind": "op", "ops": ["ts_zscore"], "args": [
            {"kind": "op", "ops": ["ts_backfill"], "args": [
                {"kind": "var", "name": "FIELD", "tag": "A"},
                {"kind": "var", "name": "LOOKBACK", "tag": "A"}]},
            {"kind": "var", "name": "LOOKBACK", "tag": "B"}]},
        {"kind": "var", "name": "GROUP", "tag": "A"}]}}

_NEUTRAL_MOMENTUM = {"version": 1, "root": {
    "kind": "op", "ops": ["group_neutralize"], "args": [
        {"kind": "op", "ops": ["ts_delta"], "args": [
            {"kind": "var", "name": "FIELD", "tag": "A"},
            {"kind": "var", "name": "LOOKBACK", "tag": "A"}]},
        {"kind": "var", "name": "GROUP", "tag": "A"}]}}

_SMOOTHED_REVERSAL = {"version": 1, "root": {
    "kind": "op", "ops": ["ts_decay_linear"], "args": [
        {"kind": "op", "ops": ["ts_av_diff"], "args": [
            {"kind": "var", "name": "FIELD", "tag": "A"},
            {"kind": "var", "name": "SLOW_LOOKBACK", "tag": "A"}]},
        {"kind": "var", "name": "FAST_LOOKBACK", "tag": "A"}]}}

_BACKFILLED_PEER_RANK = {"version": 1, "root": {
    "kind": "op", "ops": ["group_rank"], "args": [
        {"kind": "op", "ops": ["ts_rank"], "args": [
            {"kind": "op", "ops": ["ts_backfill"], "args": [
                {"kind": "op", "ops": ["divide"], "args": [
                    {"kind": "var", "name": "FIELD", "tag": "A"},
                    {"kind": "data", "name": "cap"}]},
                {"kind": "num", "value": 20}]},
            {"kind": "var", "name": "LOOKBACK", "tag": "A"}]},
        {"kind": "var", "name": "GROUP", "tag": "A"}]}}

_WINSORIZED_PEER_RANK = {"version": 1, "root": {
    "kind": "op", "ops": ["group_rank"], "args": [
        {"kind": "op", "ops": ["ts_rank"], "args": [
            {"kind": "op", "ops": ["winsorize"], "args": [
                {"kind": "op", "ops": ["divide"], "args": [
                    {"kind": "var", "name": "FIELD", "tag": "A"},
                    {"kind": "data", "name": "cap"}]}]},
            {"kind": "var", "name": "LOOKBACK", "tag": "A"}]},
        {"kind": "var", "name": "GROUP", "tag": "A"}]}}

CLASSIFICATION_TEMPLATE_MAP = {
    "earnings-surprise-type": ("Clean Then Score", _CLEAN_THEN_SCORE,
        {"LOOKBACK#A": 63, "LOOKBACK#B": 252, "GROUP#A": "subindustry"}, False),
    "analyst-estimate-type": ("Backfilled Peer Rank", _BACKFILLED_PEER_RANK,
        {"LOOKBACK#A": 21, "GROUP#A": "subindustry"}, False),
    "change-type": ("Neutral Momentum", _NEUTRAL_MOMENTUM,
        {"LOOKBACK#A": 20, "GROUP#A": "subindustry"}, False),
    "ratio-type": ("Winsorized Peer Rank", _WINSORIZED_PEER_RANK,
        {"LOOKBACK#A": 63, "GROUP#A": "subindustry"}, False),
    "count-type": ("Backfilled Peer Rank", _BACKFILLED_PEER_RANK,
        {"LOOKBACK#A": 20, "GROUP#A": "industry"}, False),
    "score-type": ("Clean Then Score", _CLEAN_THEN_SCORE,
        {"LOOKBACK#A": 63, "LOOKBACK#B": 20, "GROUP#A": "subindustry"}, False),
    "risk-type": ("Backfilled Peer Rank (reversed)", _BACKFILLED_PEER_RANK,
        {"LOOKBACK#A": 63, "GROUP#A": "subindustry"}, True),
    "valuation-type": ("Winsorized Peer Rank", _WINSORIZED_PEER_RANK,
        {"LOOKBACK#A": 126, "GROUP#A": "industry"}, False),
    "momentum-type": ("Neutral Momentum", _NEUTRAL_MOMENTUM,
        {"LOOKBACK#A": 10, "GROUP#A": "subindustry"}, False),
    "sentiment-type": ("Clean Then Score", _CLEAN_THEN_SCORE,
        {"LOOKBACK#A": 63, "LOOKBACK#B": 20, "GROUP#A": "subindustry"}, False),
    "price-type": ("Smoothed Reversal", _SMOOTHED_REVERSAL,
        {"SLOW_LOOKBACK#A": 63, "FAST_LOOKBACK#A": 20}, False),
    "level-fundamental-type": ("Winsorized Peer Rank", _WINSORIZED_PEER_RANK,
        {"LOOKBACK#A": 63, "GROUP#A": "industry"}, False),
    "diagnostic-type": ("Backfilled Peer Rank (reversed)", _BACKFILLED_PEER_RANK,
        {"LOOKBACK#A": 63, "GROUP#A": "subindustry"}, True),
    "default": ("Backfilled Peer Rank", _BACKFILLED_PEER_RANK,
        {"LOOKBACK#A": 20, "GROUP#A": "subindustry"}, False),
}


def build_expression(field_id: str, description: str, ftype: str) -> tuple[str, str, str]:
    reason = classify(description)
    template_name, tree, extra_params, needs_reverse = CLASSIFICATION_TEMPLATE_MAP[reason]

    params = dict(extra_params)
    params["field"] = field_id
    if ftype == "VECTOR":
        params["vector_op"] = "vec_avg"

    expr = render(tree, params)
    if needs_reverse:
        expr = f"reverse({expr})"
    return expr, reason, template_name
