"""Queue monitoring and alerting tasks."""

import json
from datetime import UTC, datetime

import httpx

from jarvis.celery_app import celery_app
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id


def _emit(trace_id: str, event_type: str, payload: dict[str, object]) -> None:
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type=event_type,
                component="monitoring",
                actor_type="system",
                actor_id="monitoring",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )


def _queue_depth_by_name() -> dict[str, int]:
    settings = get_settings()
    base = settings.rabbitmq_mgmt_url.strip().rstrip("/")
    if not base:
        return {}

    auth: tuple[str, str] | None = None
    if settings.rabbitmq_mgmt_user and settings.rabbitmq_mgmt_password:
        auth = (settings.rabbitmq_mgmt_user, settings.rabbitmq_mgmt_password)
    try:
        with httpx.Client(timeout=5.0, auth=auth) as client:
            response = client.get(f"{base}/api/queues")
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return {}

    depths: dict[str, int] = {}
    if not isinstance(payload, list):
        return depths
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        ready = item.get("messages_ready", 0)
        unacked = item.get("messages_unacknowledged", 0)
        if not isinstance(name, str):
            continue
        if not isinstance(ready, int):
            ready = 0
        if not isinstance(unacked, int):
            unacked = 0
        depths[name] = max(0, ready) + max(0, unacked)
    return depths


def _thresholds() -> dict[str, int]:
    settings = get_settings()
    return {
        "agent_priority": settings.queue_threshold_agent_priority,
        "agent_default": settings.queue_threshold_agent_default,
        "tools_io": settings.queue_threshold_tools_io,
        "local_llm": settings.queue_threshold_local_llm,
    }


def _send_pagerduty(summary: str, payload: dict[str, object]) -> None:
    settings = get_settings()
    if not settings.pagerduty_routing_key.strip():
        return
    body = {
        "routing_key": settings.pagerduty_routing_key,
        "event_action": "trigger",
        "payload": {
            "summary": summary,
            "source": "jarvis",
            "severity": "warning",
            "timestamp": datetime.now(UTC).isoformat(),
            "custom_details": payload,
        },
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            _ = client.post("https://events.pagerduty.com/v2/enqueue", json=body)
    except Exception:
        return


def _send_slack(summary: str, payload: dict[str, object]) -> None:
    settings = get_settings()
    webhook = settings.alert_slack_webhook_url.strip()
    if not webhook:
        return
    body = {"text": f"{summary}\n```{json.dumps(payload)}```"}
    try:
        with httpx.Client(timeout=5.0) as client:
            _ = client.post(webhook, json=body)
    except Exception:
        return


@celery_app.task(name="jarvis.tasks.monitoring.monitor_queue_backpressure")
def monitor_queue_backpressure() -> dict[str, object]:
    trace_id = new_id("trc")
    depths = _queue_depth_by_name()
    limits = _thresholds()
    alerts: list[dict[str, object]] = []
    for queue_name, threshold in limits.items():
        if threshold <= 0:
            continue
        depth = int(depths.get(queue_name, 0))
        if depth <= threshold:
            continue
        payload = {"queue": queue_name, "depth": depth, "threshold": threshold}
        alerts.append(payload)
        summary = (
            "Queue backlog threshold exceeded: "
            f"{queue_name} depth={depth} threshold={threshold}"
        )
        _send_pagerduty(summary, payload)
        _send_slack(summary, payload)
        _emit(trace_id, "queue.backpressure", payload)

    if alerts and int(depths.get("local_llm", 0)) > limits["local_llm"]:
        _emit(
            trace_id,
            "router.local_llm.shifted",
            {
                "queue": "local_llm",
                "depth": int(depths.get("local_llm", 0)),
                "action": "prefer_gemini_for_low_priority",
            },
        )
    return {"ok": True, "alerts": alerts, "depths": depths}
