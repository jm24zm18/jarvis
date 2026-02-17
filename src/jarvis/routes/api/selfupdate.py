"""Self-update patch viewer + approval routes."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import create_approval
from jarvis.selfupdate.pipeline import read_artifact, read_patch, read_state

router = APIRouter(prefix="/selfupdate", tags=["api-selfupdate"])


def _patch_dir() -> Path:
    return Path(get_settings().selfupdate_patch_dir)


@router.get("/patches")
def list_patches(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    base = _patch_dir()
    if not base.exists():
        return {"items": []}
    items: list[dict[str, str]] = []
    for path in sorted(base.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        trace_id = path.name
        try:
            state = read_state(trace_id, base)
            items.append(
                {
                    "trace_id": trace_id,
                    "state": state.get("state", "unknown"),
                    "detail": state.get("detail", ""),
                }
            )
        except Exception:
            continue
    return {"items": items}


@router.get("/patches/{trace_id}")
def patch_detail(
    trace_id: str, ctx: UserContext = Depends(require_admin)  # noqa: B008
) -> dict[str, object]:
    del ctx
    base = _patch_dir()
    try:
        state = read_state(trace_id, base)
        patch_text = read_patch(trace_id, base)
        artifact = read_artifact(trace_id, base)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"patch not found: {exc}") from exc
    return {
        "trace_id": trace_id,
        "state": state.get("state", "unknown"),
        "detail": state.get("detail", ""),
        "diff": patch_text,
        "artifact": artifact,
        "pr": artifact.get("pr", {}) if isinstance(artifact, dict) else {},
    }


@router.post("/patches/{trace_id}/approve")
def approve_patch(
    trace_id: str,
    ctx: UserContext = Depends(require_admin),  # TODO: admin-only now  # noqa: B008
) -> dict[str, str]:
    settings = get_settings()
    with get_conn() as conn:
        approval_id = create_approval(
            conn,
            action="selfupdate.apply",
            actor_id=ctx.user_id,
            target_ref=trace_id,
            ttl_minutes=max(1, int(settings.approval_ttl_minutes)),
        )
    return {"approval_id": approval_id, "action": "selfupdate.apply", "target_ref": trace_id}
