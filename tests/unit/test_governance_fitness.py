from jarvis.db.connection import get_conn
from jarvis.db.queries import latest_system_fitness_snapshot
from jarvis.tasks.maintenance import compute_system_fitness


def test_compute_system_fitness_writes_snapshot() -> None:
    result = compute_system_fitness(days=1)
    assert result["ok"] is True
    with get_conn() as conn:
        snapshot = latest_system_fitness_snapshot(conn)
    assert snapshot is not None
    metrics = snapshot["metrics"]
    assert isinstance(metrics, dict)
    assert "story_pack_pass_rate" in metrics
