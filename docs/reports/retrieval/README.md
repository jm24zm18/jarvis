# Retrieval Benchmark Artifacts

This directory stores committed benchmark outputs for state-retrieval latency and result-count stability.

## Refresh Command

```bash
uv run python scripts/retrieval_benchmark_report.py --output docs/reports/retrieval/latest.json
```

## Artifact Contract

- `latest.json` is the current baseline snapshot used for plan/evidence references.
- JSON fields include:
  - dataset metadata (`items_seeded`, `query`)
  - run metadata (`generated_at`, `run_id`, `runs`, `scenario`)
  - latency summary (`avg`, `p50`, `p95`, `max`)
  - result-count summary (`avg_count`, `min_count`, `max_count`)
