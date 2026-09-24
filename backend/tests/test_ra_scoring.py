import pytest

from alpha_harness.labs import ra_scoring as ra


def check(name, value, limit, result="FAIL"):
    return {"name": name, "result": result, "value": value, "limit": limit}


def child(sharpe, fitness, two_year):
    return [
        check("LOW_SHARPE", sharpe, 1.58),
        check("LOW_FITNESS", fitness, 1.0),
        check("LOW_2Y_SHARPE", two_year, 1.58),
        {"name": "SELF_CORRELATION", "result": "PENDING"},
    ]


def body(kids, passing, limit=2):
    result = "PASS" if passing >= limit else "FAIL"
    return {
        "is": {
            "checks": [
                {"name": ra.MIN_CHILDREN, "result": result, "limit": limit, "value": passing}
            ],
            "subregions": {f"c{i}": k for i, k in enumerate(kids)},
        }
    }


# The numbers the RA probe got back from BRAIN.
PROBE = body([child(0.08, 0.02, 0.2), child(0.27, 0.12, -0.11), child(-0.31, -0.18, -0.22)], 0)


def test_probe_scores_second_best_child():
    assert ra.score(PROBE) == pytest.approx(-0.11 / 1.58)


def test_probe_is_short_two_children():
    assert ra.constraints(PROBE) == {ra.MIN_CHILDREN: 2.0}
    assert ra.summarise("P", PROBE)["feasible"] is False


def test_two_passing_children_clear_the_line():
    b = body([child(2.0, 1.2, 1.7), child(1.9, 1.1, 1.6), child(0.1, 0.1, 0.1)], 2)
    assert ra.score(b) == pytest.approx(1.6 / 1.58)
    assert ra.constraints(b) == {ra.MIN_CHILDREN: 0.0}
    assert ra.summarise("P", b)["feasible"] is True


def test_one_child_scores_below_zero():
    assert ra.score(body([child(3.0, 2.0, 3.0)], 1)) < 0.0


def test_no_children_is_failure():
    assert ra.score({}) == ra.FAILURE
    assert ra.constraints({}) == {ra.MIN_CHILDREN: 1.0}


def test_is_parent():
    from types import SimpleNamespace as NS

    assert ra.is_parent(NS(parent=None, children=["a", "b"], settings=None))
    assert ra.is_parent(NS(parent=None, children=[], settings=NS(region="ALL")))
    assert not ra.is_parent(NS(parent="P", children=[], settings=NS(region="ALL")))
    assert not ra.is_parent(NS(parent=None, children=[], settings=NS(region="USA")))
