# Security Risk Acceptance Register

## RSK-2026-02-18-AJV6

- Date accepted: 2026-02-18
- Scope: `web/package-lock.json` (`ajv@6.12.6`, transitive via `eslint`/`@eslint/eslintrc`)
- Advisory: `GHSA-2g4f-4pwh-qvx6`
- Current exposure: development dependency graph only (lint/test toolchain), no runtime production dependency path.
- Why not remediated immediately:
  - Current `eslint@9.39.2` dependency chain still requires `ajv@^6.12.4`.
  - Forcing `ajv@8` via overrides is incompatible with the upstream dependency contract.
- Temporary controls:
  - Keep lockfile pinned and audited in CI/local evidence runs.
  - Track upstream ESLint ecosystem migration to `ajv>=8.18.0`.
- Sunset date: 2026-04-30
- Exit criteria:
  1. Upgrade to dependency versions that no longer require `ajv@6.x`.
  2. Regenerate `web/package-lock.json`.
  3. Re-run `osv-scanner --lockfile=web/package-lock.json` with no `ajv` finding.
