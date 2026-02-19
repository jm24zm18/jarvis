"""Generate a deterministic retrieval benchmark artifact for state-search latency."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from types import MethodType

from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_channel, ensure_open_thread, ensure_system_state, ensure_user
from jarvis.memory.service import MemoryService


def _seed_state_item(
    conn,
    *,
    uid: str,
    thread_id: str,
    text: str,
    tier: str,
    seen_at: str,
) -> None:
    conn.execute(
        (
            "INSERT INTO state_items("
            "uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, confidence, "
            "replaced_by, supersession_evidence, conflict, pinned, source, created_at, "
            "last_seen_at, updated_at, tier, importance_score, access_count, conflict_count, "
            "agent_id, last_accessed_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            uid,
            thread_id,
            text,
            "active",
            "decision",
            "[]",
            "[]",
            "high",
            None,
            None,
            0,
            0,
            "benchmark",
            seen_at,
            seen_at,
            seen_at,
            tier,
            0.7,
            0,
            0,
            "main",
            seen_at,
        ),
    )


def _prepare_fixture(conn, run_id: str, item_count: int) -> str:
    ensure_system_state(conn)
    user_id = ensure_user(conn, f"retrieval_benchmark_{run_id}")
    channel_id = ensure_channel(conn, user_id, "web")
    thread_id = ensure_open_thread(conn, user_id, channel_id)
    for idx in range(item_count):
        tier = "working" if idx % 3 == 0 else ("episodic" if idx % 3 == 1 else "semantic_longterm")
        _seed_state_item(
            conn,
            uid=f"bench_{run_id}_{idx:04d}",
            thread_id=thread_id,
            text=f"benchmark query item {idx} for retrieval latency and quality checks",
            tier=tier,
            seen_at=f"2026-02-10T00:{idx % 60:02d}:00+00:00",
        )
    return thread_id


def _install_fast_embedding(service: MemoryService) -> None:
    def _fast_embed(self, conn, text: str) -> list[float]:
        del self, conn
        text = text.strip().lower()
        return [0.1, 0.2, 0.3, float(len(text) % 11) / 10.0]

    service._embed_text_cached = MethodType(_fast_embed, service)  # type: ignore[method-assign]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="docs/reports/retrieval/latest.json",
        help="Path to write benchmark artifact JSON.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=8,
        help="Number of timed retrieval runs to execute.",
    )
    parser.add_argument(
        "--items",
        type=int,
        default=120,
        help="Number of synthetic state items to seed in benchmark thread.",
    )
    args = parser.parse_args()

    iterations = max(1, args.iterations)
    item_count = max(20, args.items)
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    service = MemoryService()
    _install_fast_embedding(service)
    latencies_ms: list[float] = []
    result_counts: list[int] = []

    with get_conn() as conn:
        thread_id = _prepare_fixture(conn, run_id, item_count)
        for _ in range(iterations):
            t0 = time.perf_counter()
            rows = service.search_state(
                conn,
                thread_id,
                "benchmark query",
                k=20,
                min_score=0.0,
                actor_id="main",
            )
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            result_counts.append(len(rows))

    latencies_sorted = sorted(latencies_ms)
    p95_index = min(len(latencies_sorted) - 1, round(0.95 * (len(latencies_sorted) - 1)))
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "scenario": "state_search_rrf_latency",
        "dataset": {"items_seeded": item_count, "query": "benchmark query"},
        "runs": iterations,
        "latency_ms": {
            "avg": round(statistics.mean(latencies_ms), 3),
            "p50": round(statistics.median(latencies_ms), 3),
            "p95": round(latencies_sorted[p95_index], 3),
            "max": round(max(latencies_ms), 3),
        },
        "results": {
            "avg_count": round(statistics.mean(result_counts), 3),
            "min_count": min(result_counts),
            "max_count": max(result_counts),
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote retrieval benchmark artifact: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
