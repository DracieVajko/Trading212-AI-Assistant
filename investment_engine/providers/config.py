"""Typed construction specs for provider factory helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from investment_engine.providers.base import BaseLLMProvider


@dataclass(frozen=True)
class CloudProviderSpec:
    """One declarative construction spec for an OpenAI-compatible cloud provider."""

    factory: Callable[..., BaseLLMProvider]
    api_key: str
    model: str
    base_url: str
    max_output_tokens: int

    def build(self) -> BaseLLMProvider:
        return self.factory(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            max_output_tokens=self.max_output_tokens,
        )
