# Security Policy

## Reporting

Report vulnerabilities privately to repository maintainers. Do not open public issues containing exploit details or secrets.

## Security Model Highlights

- Auth: bearer session tokens mapped to `UserContext` with `user`/`admin` role.
- RBAC: admin-only routes for lockdown, permissions, and self-update approvals.
- Ownership enforcement: non-admin users are scoped to resources tied to their threads.
- Tool runtime: deny-by-default with policy checks before execution.

## Lockdown and Blast-Radius Controls

- Global lockdown blocks non-safe tools.
- Restart mode blocks tool execution.
- Unlock requires admin-controlled code path.

## Exec Host Safeguards

Configured in `src/jarvis/config.py`:

- Timeout caps (`EXEC_HOST_TIMEOUT_MAX_SECONDS`)
- Memory caps (`EXEC_HOST_MAX_MEMORY_MB`)
- CPU caps (`EXEC_HOST_MAX_CPU_SECONDS`)
- Output caps (`EXEC_HOST_MAX_OUTPUT_BYTES`)
- Allowed CWD prefixes and env allowlist restrictions

## Webhook and API Protections

- WhatsApp verify token validation.
- Rate limiting on message/webhook surfaces.
- CORS allowlist via `WEB_CORS_ORIGINS`.

## Agent Notes

- Never commit real secrets in docs or `.env.example`.
- Review ownership checks for all new thread-linked routes.

## Related Docs

- `docs/architecture.md`
- `docs/change-safety.md`
- `docs/runbook.md`
