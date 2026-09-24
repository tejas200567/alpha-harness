"""
Field-level evidence from kb_graph.db -- a community/paper knowledge graph
built separately (56,719 edges: real PERFORMS_IN history with n/mean_sharpe/
mean_fitness, plus WORKS_WELL_WITH/FAILS_WITH neutralization signals).
Read-only; the harness never writes to this graph.
"""
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / ".alpha-harness" / "kb_graph.db"


def _connect() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def field_intelligence(field_id: str) -> dict[str, Any]:
    con = _connect()
    if con is None:
        return {"performance": [], "neutralization_works": [], "neutralization_fails": []}

    performance = [
        {"scope": r["dst"], "n": r["n"], "mean_sharpe": r["mean_sharpe"], "mean_fitness": r["mean_fitness"]}
        for r in con.execute(
            "SELECT dst, n, mean_sharpe, mean_fitness FROM kb_edges "
            "WHERE src_type = 'Field' AND src = ? AND edge_type = 'PERFORMS_IN' "
            "ORDER BY mean_sharpe DESC",
            (field_id,),
        )
    ]
    works = [
        {"neutralization": r["dst"], "n": r["n"], "mean_sharpe": r["mean_sharpe"], "mean_fitness": r["mean_fitness"]}
        for r in con.execute(
            "SELECT dst, n, mean_sharpe, mean_fitness FROM kb_edges "
            "WHERE src_type = 'Field' AND src = ? AND edge_type = 'WORKS_WELL_WITH' AND dst_type = 'Neutralization'",
            (field_id,),
        )
    ]
    fails = [
        {"neutralization": r["dst"], "n": r["n"], "mean_sharpe": r["mean_sharpe"], "mean_fitness": r["mean_fitness"]}
        for r in con.execute(
            "SELECT dst, n, mean_sharpe, mean_fitness FROM kb_edges "
            "WHERE src_type = 'Field' AND src = ? AND edge_type = 'FAILS_WITH' AND dst_type = 'Neutralization'",
            (field_id,),
        )
    ]
    con.close()
    return {"performance": performance, "neutralization_works": works, "neutralization_fails": fails}
