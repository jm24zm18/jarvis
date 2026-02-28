---
slug: web-research
pinned: false
---

# Web Research

## Purpose
Standardize external research so outputs are current, source-ranked, and auditable.

## Key Facts
- Use a staged query loop: broad discovery, constrained refinement, source-specific confirmation.
- Prefer source ranking: official docs/specs/repositories first, then primary evidence, then reputable secondary summaries.
- For volatile topics (news, prices, policies, releases), verify freshness with explicit publish/update dates.
- Resolve contradictions by finding the nearest primary source and stating confidence + uncertainty.
- Treat missing or stale evidence as a first-class result; do not overstate conclusions.

## Usage
1. Start with one broad query to identify canonical sources.
2. Refine using constraints: exact product/version, date window, and domain filters when possible.
3. Validate each key claim with at least two independent sources unless a primary source is authoritative.
4. Record evidence per claim:
   - `claim`
   - `source_url`
   - `source_type` (official, primary, secondary)
   - `published_or_updated_date`
   - `confidence` (high/medium/low)
5. If evidence conflicts, prioritize official/primary material and note disagreement explicitly.
6. If evidence is insufficient, stop and return an "insufficient evidence" outcome with next queries to run.

## Examples
```text
Technical-doc flow:
1) Discover: "<library> official docs rate limit"
2) Refine: "<library> vX.Y rate limit endpoint"
3) Confirm: docs + source repo issue/changelog
4) Output: behavior summary with version/date scope
```

```text
News/market flow:
1) Discover: "<topic> latest announcement"
2) Refine by recency + official domain
3) Cross-check with at least one independent outlet
4) Output includes exact event date and confidence level
```

## Notes
- Avoid long quotes; synthesize and cite.
- Always state when a conclusion is inferred rather than directly specified by sources.
