---
slug: session-management
pinned: false
---

# Session Management

## Purpose
Define deterministic agent routing, handoff, and recovery behavior for multi-step conversations.

## Key Facts
- Route decisions are evaluated in this order: user intent match, policy/tool eligibility, ownership scope, then confidence.
- Handoff is required when the current agent lacks allowed tools, fails policy checks, or cannot meet confidence threshold.
- Handoff packets must preserve thread/session continuity using the same `thread_id` plus compact state summary.
- Every handoff must include unresolved actions and open risks so the receiver can continue without re-discovery.
- If handoff fails or times out, control returns to `main` with a user-visible escalation message and no policy bypass.
- Ownership and RBAC boundaries apply during handoff exactly as they do during direct handling.

## Usage
1. Evaluate whether the current agent can complete the request with allowed tools and scope.
2. If not, prepare a handoff packet with required fields:
   - `thread_id` (required)
   - `from_agent` (required)
   - `to_agent` (required)
   - `goal` (required)
   - `state_summary` (required, concise)
   - `unresolved_actions` (required)
   - `constraints` (optional)
   - `artifacts` (optional: paths, IDs, links)
3. Send handoff and wait for explicit accept/reject from target agent.
4. On accept, transfer execution ownership and log a handoff event.
5. On reject/failure/timeout, route back to `main`, include failure reason, and continue with safest fallback.
6. On completion, require return-handoff payload with outcome, outputs, and remaining follow-ups.

## Examples
```text
Valid handoff:
main -> release_ops
Reason: deployment runbook + privileged deploy tool needed.
Packet includes thread_id, current rollout status, and pending checks.
```

```text
Valid return handoff:
release_ops -> main
Outcome: deploy complete, health checks green, follow-up monitor window 30m.
```

```text
Denied handoff:
feature_builder -> data_admin
Reason: target tool requires admin scope and caller session is non-admin.
Action: reject, log policy deny, return to main with constrained alternative.
```

## Notes
- Never bypass `policy/engine.py` or ownership checks to force a handoff.
- Prefer smaller, explicit `state_summary` over full transcript forwarding.
