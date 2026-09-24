from alpha_harness.labs import template

COVERAGE = {
    "a": frozenset({"USA", "EUR", "ASI", "CHN"}),
    "b": frozenset({"USA", "DEU"}),
    "c": frozenset({"GLB", "EUR"}),
}


def test_ra_filter_keeps_fields_in_two_ra_regions():
    fields = {"a": "MATRIX", "b": "MATRIX", "c": "VECTOR", "d": "MATRIX"}
    kept, regions, narrow, unknown = template.ra_filter(fields, COVERAGE)
    assert kept == {"a": "MATRIX", "c": "VECTOR"}
    assert regions == {"a": ["ASI", "EUR", "USA"], "c": ["EUR", "GLB"]}
    assert (narrow, unknown) == (1, 1)


def test_ra_common_finds_pairs_meeting_in_one_region():
    regions = {"a": ["ASI", "EUR", "USA"], "c": ["EUR", "GLB"]}
    assert template.ra_common(["a"], regions) == ["ASI", "EUR", "USA"]
    assert template.ra_common(["a", "c"], regions) == ["EUR"]
