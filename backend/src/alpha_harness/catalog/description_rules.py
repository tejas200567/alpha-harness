"""
Description-aware template selection -- ported from
~/wqbrain/build_all_regions_descaware.py.
"""
import re

METADATA_EXCLUSION_PATTERNS = re.compile(
    r"\btimestamp\b|\bunix epoch\b|\bunique identifier\b|\bstart time\b|\bend time\b"
    r"|\bcurrency code\b|\biso 4217\b|\bisexcluded\b|\bprevalue\b|\breceivetime\b"
    r"|\bage of\b.*\bestimates? in days\b|\bdictionary of\b|\breporting period\b"
    r"|\bevent start time\b|\bingestion\b|\btext_full\b|\bdisplay label\b"
    r"|lastupdated|\blast.updated\b|\bin gmt\b|\bin utc\b|\bnarrative\b",
    re.IGNORECASE,
)

DESCRIPTION_RULES = [
    (r"\bsurprise\b", "group_rank(ts_decay_linear(ts_zscore(ts_backfill({F},63),252),30),subindustry)", "earnings-surprise-type"),
    (r"\bpredicted\b|\bforecast\b|smart.?estimates?|\bconsensus\b", "group_rank(ts_decay_linear(ts_returns(ts_backfill({F},63),21),10),subindustry)", "analyst-estimate-type"),
    (r"\bchange\b|\bdelta\b|\bgrowth\b|\brevision\b", "group_rank(ts_delta(ts_backfill({F},63),20),subindustry)", "change-type"),
    (r"\bratio\b|\bpercent(age)?\b|\bpct\b|\bproportion\b", "group_rank(ts_backfill({F},63),subindustry)", "ratio-type"),
    (r"\bcount\b|\bnumber\b|\bnum\b", "group_rank(ts_backfill({F},20),industry)", "count-type"),
    (r"\bscore\b|\bindex\b|\brating\b|\brank\b", "group_zscore(winsorize(ts_backfill({F},63),std=4),subindustry)", "score-type"),
    (r"\bvolatility\b|\bvariance\b|\bstd\b|\bstandard deviation\b|\brisk\b|\bstability\b|\bvariability\b",
     "reverse(group_rank(ts_backfill({F},63),subindustry))", "risk-type"),
    (r"\byield\b|\bvalue\b|\bmultiple\b|\bexpected return\b|\brate of return\b", "group_rank(ts_backfill({F},126),industry)", "valuation-type"),
    (r"\bmomentum\b|\btrend\b|\bacceleration\b", "group_rank(ts_delta(ts_backfill({F},63),10),subindustry)", "momentum-type"),
    (r"\bsentiment\b|\btone\b|\bbuzz\b|\bpositive signal\b|\bnegative signal\b", "group_rank(ts_decay_linear(ts_zscore(ts_backfill({F},63),20),5),subindustry)", "sentiment-type"),
    (r"\bprice\b|\b52.?week\b|\bhigh\b|\blow\b", "group_rank(ts_returns(ts_backfill({F},63),20),subindustry)", "price-type"),
    (r"\bnet\b|\btotal\b|\baggregat|\bassets\b|\bdebt\b|\bequity\b|\bexpense\b|\bincome\b"
     r"|\brevenue\b|\bcash flow\b|\bimpairment\b|\bwrite.?down\b|\bwrite.?off\b"
     r"|\binterest\b|\bsum\b|\breduction\b|\bffo\b|\bminority\b",
     "group_zscore(winsorize(ts_backfill({F},63),std=4),industry)", "level-fundamental-type"),
    (r"\bdeviation\b|\berror\b|\bmad\b|\bmae\b", "reverse(group_rank(ts_backfill({F},63),subindustry))", "diagnostic-type"),
]
DEFAULT = ("group_rank(ts_backfill({F},20),subindustry)", "default")


def is_metadata_field(description: str) -> bool:
    return bool(METADATA_EXCLUSION_PATTERNS.search(description or ""))


def pick_template(description: str, ftype: str) -> tuple[str, str]:
    desc_l = (description or "").lower()
    for pattern, template, reason in DESCRIPTION_RULES:
        if re.search(pattern, desc_l):
            if ftype == "VECTOR":
                template = template.replace("{F}", "vec_avg({F})")
            return template, reason
    template, reason = DEFAULT
    if ftype == "VECTOR":
        template = template.replace("{F}", "vec_avg({F})")
    return template, reason


def build_expression(field_id: str, description: str, ftype: str) -> tuple[str, str]:
    template, reason = pick_template(description, ftype)
    return template.format(F=field_id), reason
