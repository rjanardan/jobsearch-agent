"""ModelGateway interface.

The orchestration and tool layers depend on this abstraction, never on a
specific router. v0.1 ships a LiteLLM-backed implementation; a homegrown
gateway can slot in behind the same interface without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ModelResponse:
    text: str
    model: str
    usage: dict = field(default_factory=dict)  # {"input_tokens": n, "output_tokens": n}
    latency_ms: int = 0


class ModelGateway(ABC):
    """Minimal contract every provider router must satisfy."""

    @abstractmethod
    def complete(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        """Chat completion. `messages` use OpenAI message shape."""

    @abstractmethod
    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        """Batch text embeddings."""
