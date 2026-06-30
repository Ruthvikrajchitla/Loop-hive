"""
LoopHive — LLM Router

Cascading router across free-tier LLM providers.
Automatically rotates between providers when rate limits are hit.
Tracks usage per-provider to maximize free-tier throughput.
"""

from __future__ import annotations

import asyncio
import json
import random
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
    is_exhausted: bool = False  # True only when the daily quota (max_rpd) is spent
    cooldown_until: float = 0.0  # Short-lived 429 backoff (per-minute), not a daily ban

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
        """Check if this provider can accept another request right now."""
        self.reset_minute_if_needed()
        self.reset_day_if_needed()

        if time.time() < self.cooldown_until:
            return False
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

    def set_cooldown(self, seconds: float):
        """Temporarily bench this provider (e.g. after a 429) without a full daily ban."""
        self.cooldown_until = max(self.cooldown_until, time.time() + seconds)

    def seconds_until_available(self, provider: LLMProviderConfig) -> float:
        """How long until this provider could serve again. ``inf`` means not this cycle."""
        self.reset_minute_if_needed()
        self.reset_day_if_needed()
        now = time.time()

        # Daily quota spent or repeatedly erroring → won't recover on a short backoff.
        if self.is_exhausted or self.requests_today >= provider.max_rpd:
            return float("inf")
        if self.consecutive_errors >= 5:
            return float("inf")

        waits: list[float] = []
        if now < self.cooldown_until:
            waits.append(self.cooldown_until - now)
        if self.requests_this_minute >= provider.max_rpm:
            waits.append(max(0.0, 60.0 - (now - self.minute_reset_time)))
        return min(waits) if waits else 0.0

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

    # Tasks that produce long-form prose / analysis → quality models, not the 8B.
    HEAVY_TASKS = {"content_writer", "product_creator", "research_agent"}

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

        Cascades through providers by priority. A 429 only benches a provider for a
        short cooldown (the rate-limit window, honoring ``Retry-After``) rather than
        for the whole day. If every provider is temporarily limited, it waits with
        exponential-ish backoff + jitter and retries the cascade before giving up.
        """
        max_attempts = 4
        last_errors: list[str] = []

        # For writing-heavy tasks, try quality models first and demote weak ones
        # (e.g. Llama-8B) to last resort so product/article bodies stay high quality.
        if task_type in self.HEAVY_TASKS:
            providers = sorted(self.providers, key=lambda p: (0 if p.quality else 1, p.priority))
        else:
            providers = self.providers

        for attempt in range(1, max_attempts + 1):
            errors: list[str] = []

            for provider in providers:
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
                        retry_after = self._parse_retry_after(e.response) or 60.0
                        usage.set_cooldown(retry_after)
                        logger.warning(
                            "provider_rate_limited",
                            provider=provider.name,
                            status=429,
                            cooldown_seconds=round(retry_after, 1),
                        )
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

            last_errors = errors

            # Full pass with no success. If some provider is only *temporarily*
            # limited (cooldown / per-minute cap), wait it out and try again.
            recovery_wait = self._min_recovery_wait()
            if attempt < max_attempts and recovery_wait != float("inf"):
                sleep_for = min(recovery_wait, 30.0) + random.uniform(0.0, 1.0)
                logger.info(
                    "llm_router_backoff",
                    attempt=attempt,
                    sleep_seconds=round(sleep_for, 2),
                )
                await asyncio.sleep(sleep_for)
                continue
            break

        raise RuntimeError(
            f"All LLM providers exhausted or errored. Errors: {'; '.join(last_errors)}"
        )

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        """Parse a Retry-After header (delta-seconds form) into seconds, if present."""
        value = response.headers.get("retry-after")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None

    def _min_recovery_wait(self) -> float:
        """Shortest time until any provider can serve again (``inf`` if none soon)."""
        waits = [
            self.usage[p.name].seconds_until_available(p)
            for p in self.providers
        ]
        return min(waits) if waits else float("inf")

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
            cooldown_remaining = max(0.0, usage.cooldown_until - time.time())
            summary[provider.name] = {
                "model": provider.model,
                "requests_today": usage.requests_today,
                "max_rpd": provider.max_rpd,
                "remaining_today": max(0, provider.max_rpd - usage.requests_today),
                "is_exhausted": usage.is_exhausted,
                "cooldown_seconds": round(cooldown_remaining, 1),
                "consecutive_errors": usage.consecutive_errors,
            }
        return summary


# Global LLM router instance
llm_router = LLMRouter()
