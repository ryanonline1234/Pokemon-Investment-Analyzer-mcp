
import os
import asyncio
from typing import Optional, AsyncIterator


class AIAdapter:
    """Simple AI adapter placeholder with async streaming.

    Use `AI_PROVIDER` env var to control provider. This implementation
    yields deterministic chunks when no provider is configured. Extend
    this class to call real APIs (Grok/Claude/OpenAI) with streaming.
    """

    def __init__(self, provider: Optional[str] = None, api_key: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key

    @classmethod
    def from_env(cls):
        provider = os.environ.get("AI_PROVIDER")
        api_key = os.environ.get("AI_API_KEY")
        return cls(provider=provider, api_key=api_key)

    async def stream_explain(self, metrics: dict) -> AsyncIterator[str]:
        """Async generator that yields explanation chunks.

        For now this produces a simple deterministic explanation in small
        chunks. Replace with provider-specific streaming calls as needed.
        """
        if not self.provider:
            bp = metrics.get("box_price")
            sold = metrics.get("sold_count_30d")
            top = metrics.get("top_chase", {}).get("sum_top")
            text = f"Box price: {bp}. 30-day sold: {sold}. Top cards total value: {top}."
            # yield in small chunks
            for i in range(0, len(text), 30):
                await asyncio.sleep(0.01)
                yield text[i : i + 30]
            return

        # TODO: implement provider integrations with streaming APIs
        raise NotImplementedError("AI provider streaming not implemented")

    def explain(self, metrics: dict) -> str:
        """Synchronous helper that collects the async stream and returns full text.

        This is a convenience for synchronous callers (e.g., HTTP endpoints).
        """
        try:
            return asyncio.run(self._collect_stream(metrics))
        except RuntimeError:
            # If an event loop is already running (rare for sync endpoints in tests),
            # fall back to a simple non-streaming construction.
            bp = metrics.get("box_price")
            sold = metrics.get("sold_count_30d")
            top = metrics.get("top_chase", {}).get("sum_top")
            return f"Box price: {bp}. 30-day sold: {sold}. Top cards total: {top}."

    async def _collect_stream(self, metrics: dict) -> str:
        parts = []
        async for chunk in self.stream_explain(metrics):
            parts.append(chunk)
        return "".join(parts)

