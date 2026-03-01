"""RLM configuration helpers."""

from dataclasses import dataclass

from jarvis.config import Settings


@dataclass(frozen=True)
class RLMConfig:
    feature_build_use_rlm: bool
    rlm_enabled: bool
    context_files_limit: int
    context_token_limit: int
    prompt_token_limit: int
    validation_attempts: int
    max_attempts: int
    max_refinements: int
    timeout_s: int
    budget_per_1k_tokens: float

    @property
    def active(self) -> bool:
        return bool(self.feature_build_use_rlm and self.rlm_enabled)


def build_rlm_config(settings: Settings) -> RLMConfig:
    return RLMConfig(
        feature_build_use_rlm=bool(settings.feature_build_use_rlm),
        rlm_enabled=bool(settings.rlm_enabled),
        context_files_limit=max(1, int(settings.rlm_context_files_limit)),
        context_token_limit=max(512, int(settings.rlm_context_token_limit)),
        prompt_token_limit=max(512, int(settings.rlm_prompt_token_limit)),
        validation_attempts=max(1, int(settings.rlm_validation_attempts)),
        max_attempts=max(1, int(settings.rlm_max_attempts)),
        max_refinements=max(0, int(settings.rlm_max_refinements)),
        timeout_s=max(10, int(settings.rlm_timeout_s)),
        budget_per_1k_tokens=max(0.0, float(settings.rlm_budget_per_1k_tokens)),
    )
