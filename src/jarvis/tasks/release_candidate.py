"""Release candidate evidence builder."""

from __future__ import annotations

from jarvis.config import get_settings
from jarvis.tasks.story_runner import latest_story_pack_status


def build_release_candidate() -> dict[str, object]:
    settings = get_settings()
    if int(settings.release_candidate_agent_enabled) != 1:
        return {"status": "disabled"}
    required_pack = settings.user_simulator_required_pack.strip() or "p0"
    story_status = latest_story_pack_status(required_pack)
    return {
        "status": "ready" if story_status == "passed" else "blocked",
        "required_story_pack": required_pack,
        "story_status": story_status,
        "checks": {
            "lint": "required",
            "typecheck": "required",
            "test_gates": "required",
            "security": "required",
            "migrations": "required",
        },
    }

