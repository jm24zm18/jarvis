"""Async RLM service that calls the provider router and captures telemetry."""

from __future__ import annotations

import asyncio
import logging
from hashlib import sha256
from typing import Any

from jarvis.config import Settings
from jarvis.orchestrator.prompt_builder import estimate_tokens
from jarvis.providers.factory import build_fallback_provider, build_primary_provider
from jarvis.providers.router import ProviderRouter
from jarvis.rlm.config import build_rlm_config
from jarvis.rlm.decomposer import (
    ContextFile,
    build_decompose_prompt,
    build_repair_prompt,
    parse_decompose_result,
    validate_plan,
)

logger = logging.getLogger(__name__)


class AsyncRLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.config = build_rlm_config(settings)

    async def decompose(
        self,
        feature_id: str,
        feature_title: str,
        feature_description: str,
        context_files: list[ContextFile],
    ) -> dict[str, Any]:
        prompt, allowed_paths = build_decompose_prompt(
            feature_title, feature_description, context_files
        )
        router = ProviderRouter(
            build_primary_provider(self.settings),
            build_fallback_provider(self.settings),
        )
        attempts = 0
        repair_attempts = 0
        current_prompt = prompt
        last_raw = ""
        last_json = ""
        validation_errors: list[str] = []
        while attempts < self.config.validation_attempts:
            attempts += 1
            try:
                response, provider_used, primary_error = await asyncio.wait_for(
                    router.generate(
                        [{"role": "user", "content": current_prompt}],
                        tools=None,
                        temperature=0.2,
                        max_tokens=self.config.prompt_token_limit,
                    ),
                    timeout=self.config.timeout_s,
                )
            except TimeoutError:
                return {
                    "status": "timeout",
                    "error": "rlm_decompose_timeout",
                    "attempts": attempts,
                    "prompt_hash": _hash_text(current_prompt),
                    "raw": last_raw,
                    "validation_errors": validation_errors,
                }
            raw_text = response.text or ""
            usage = _compute_usage(current_prompt, raw_text, self.config.budget_per_1k_tokens)
            plan, snippet = parse_decompose_result(raw_text)
            last_raw = raw_text
            last_json = snippet or ""
            if plan is None:
                validation_errors = ["RLM output is not parseable JSON."]
            else:
                validation_errors, normalized = validate_plan(plan, allowed_paths)
                if not validation_errors:
                    return {
                        "status": "success",
                        "subtasks": normalized,
                        "raw": raw_text,
                        "prompt": current_prompt,
                        "prompt_hash": _hash_text(current_prompt),
                        "response_text": raw_text,
                        "usage": usage,
                        "attempts": attempts,
                        "provider": provider_used,
                    }
            if (
                validation_errors
                and repair_attempts < self.config.max_refinements
                and attempts < self.config.validation_attempts
            ):
                repair_attempts += 1
                current_prompt = build_repair_prompt(
                    last_json or raw_text,
                    validation_errors,
                    allowed_paths,
                )
                continue
            break
        return {
            "status": "invalid",
            "error": "validation_failed",
            "validation_errors": validation_errors,
            "raw": last_raw,
            "prompt": current_prompt,
            "prompt_hash": _hash_text(current_prompt),
            "attempts": attempts,
            "usage": usage if 'usage' in locals() else {"prompt_tokens": 0, "response_tokens": 0},
        }


def _hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _compute_usage(prompt: str, response: str, budget_per_1k: float) -> dict[str, Any]:
    prompt_tokens = estimate_tokens(prompt)
    response_tokens = estimate_tokens(response)
    budget = (prompt_tokens + response_tokens) / 1000.0 * budget_per_1k
    return {
        "prompt_tokens": prompt_tokens,
        "response_tokens": response_tokens,
        "budget_estimate": round(budget, 4),
    }
