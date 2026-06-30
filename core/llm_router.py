"""
LoopHive — LLM Router

Cascading router across free-tier LLM providers.
Automatically rotates between providers when rate limits are hit.
Tracks usage per-provider to maximize free-tier throughput.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from core.config import LLMProviderConfig, config

logger = structlog.get_logger(__name__)


@dataclass
class ProviderUsage:
    """Tracks real-time usage for a single provider."""
    requests_this_minute: int = 0
    requests_today: int = 0
    tokens_this_minute: int = 0
    minute_reset_time: float = 0.0
    day_reset_time: float = 0.0
    consecutive_errors: int = 0
    is_exhausted: bool = False

    def reset_minute_if_needed(self):
        now = time.time()
        if now - self.minute_reset_time >= 60:
            self.requests_this_minute = 0
            self.tokens_this_minute = 0
            self.minute_reset_time = now

    def reset_day_if_needed(self):
        now = time.time()
        if now - self.day_reset_time >= 86400:  # 24 hours
            self.requests_today = 0
            self.is_exhausted = False
            self.day_reset_time = now

    def can_make_request(self, provider: LLMProviderConfig) -> bool:
        """Check if this provider can accept another request."""
        self.reset_minute_if_needed()
        self.reset_day_if_needed()

        if self.is_exhausted:
            return False
        if self.requests_this_minute >= provider.max_rpm:
            return False
        if self.requests_today >= provider.max_rpd:
            self.is_exhausted = True
            return False
        if self.consecutive_errors >= 5:
            return False

        return True

    def record_request(self, tokens_used: int = 0):
        """Record a successful request."""
        self.requests_this_minute += 1
        self.requests_today += 1
        self.tokens_this_minute += tokens_used
        self.consecutive_errors = 0

    def record_error(self):
        """Record a failed request."""
        self.consecutive_errors += 1


class LLMRouter:
    """
    Smart cascading router across free-tier LLM providers.

    Strategy:
    1. Try the highest-priority provider first
    2. If rate-limited (429), cascade to next provider
    3. Track usage to avoid hitting limits
    4. Exponential backoff on errors
    5. Daily usage reset for each provider
    """

    def __init__(self, providers: list[LLMProviderConfig] | None = None):
        self.providers = providers or config.get_llm_providers()
        self.usage: dict[str, ProviderUsage] = {
            p.name: ProviderUsage(
                minute_reset_time=time.time(),
                day_reset_time=time.time(),
            )
            for p in self.providers
        }
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        task_type: str = "general",
    ) -> dict:
        """
        Generate a completion using the best available provider.

        Returns dict with keys: content, provider, model, tokens_used
        """
        errors = []

        for provider in self.providers:
            usage = self.usage[provider.name]

            if not usage.can_make_request(provider):
                logger.debug(
                    "provider_skipped",
                    provider=provider.name,
                    reason="rate_limited_or_exhausted",
                )
                continue

            try:
                result = await self._call_provider(
                    provider, messages, temperature, max_tokens, json_mode
                )
                usage.record_request(result.get("tokens_used", 0))
                logger.info(
                    "llm_request_success",
                    provider=provider.name,
                    model=provider.model,
                    tokens=result.get("tokens_used", 0),
                )
                return result

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning(
                        "provider_rate_limited",
                        provider=provider.name,
                        status=429,
                    )
                    usage.is_exhausted = True
                    errors.append(f"{provider.name}: rate limited (429)")
                    continue
                else:
                    usage.record_error()
                    errors.append(f"{provider.name}: HTTP {e.response.status_code}")
                    logger.error(
                        "provider_http_error",
                        provider=provider.name,
                        status=e.response.status_code,
                    )
                    continue

            except Exception as e:
                usage.record_error()
                errors.append(f"{provider.name}: {str(e)[:100]}")
                logger.error(
                    "provider_error",
                    provider=provider.name,
                    error=str(e)[:200],
                )
                continue

        # All providers exhausted
        raise RuntimeError(
            f"All LLM providers exhausted or errored. Errors: {'; '.join(errors)}"
        )

    async def _call_provider(
        self,
        provider: LLMProviderConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> dict:
        """Make the actual API call to a provider."""
        client = await self._get_client()

        if provider.name == "gemini":
            return await self._call_gemini(
                client, provider, messages, temperature, max_tokens
            )
        else:
            # OpenAI-compatible API (Groq, OpenRouter, Cerebras, Grok)
            return await self._call_openai_compatible(
                client, provider, messages, temperature, max_tokens, json_mode
            )

    async def _call_gemini(
        self,
        client: httpx.AsyncClient,
        provider: LLMProviderConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """Call Google Gemini API."""
        url = (
            f"{provider.base_url}/models/{provider.model}:generateContent"
            f"?key={provider.api_key}"
        )

        # Convert messages to Gemini format
        contents = []
        system_instruction = None

        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}],
                })

        # Ensure at least one user message
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        response = await client.post(url, json=body)
        response.raise_for_status()
        data = response.json()

        # Extract text from response
        text = ""
        if "candidates" in data and data["candidates"]:
            candidate = data["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                text = candidate["content"]["parts"][0].get("text", "")

        tokens_used = data.get("usageMetadata", {}).get("totalTokenCount", 0)

        return {
            "content": text,
            "provider": provider.name,
            "model": provider.model,
            "tokens_used": tokens_used,
        }

    async def _call_openai_compatible(
        self,
        client: httpx.AsyncClient,
        provider: LLMProviderConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> dict:
        """Call OpenAI-compatible API (Groq, OpenRouter, Cerebras, Grok)."""
        url = f"{provider.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter requires extra headers
        if provider.name == "openrouter":
            headers["HTTP-Referer"] = "https://loophive.app"
            headers["X-Title"] = "LoopHive"

        body: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if json_mode and provider.supports_json:
            body["response_format"] = {"type": "json_object"}

        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        tokens_used = data.get("usage", {}).get("total_tokens", 0)

        return {
            "content": content,
            "provider": provider.name,
            "model": provider.model,
            "tokens_used": tokens_used,
        }

    def get_usage_summary(self) -> dict:
        """Get current usage across all providers."""
        summary = {}
        for provider in self.providers:
            usage = self.usage[provider.name]
            usage.reset_minute_if_needed()
            usage.reset_day_if_needed()
            summary[provider.name] = {
                "model": provider.model,
                "requests_today": usage.requests_today,
                "max_rpd": provider.max_rpd,
                "remaining_today": max(0, provider.max_rpd - usage.requests_today),
                "is_exhausted": usage.is_exhausted,
                "consecutive_errors": usage.consecutive_errors,
            }
        return summary


# Global LLM router instance
llm_router = LLMRouter()
