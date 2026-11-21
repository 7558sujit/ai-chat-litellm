"""LiteLLM wrapper: key pool, auto-fallback, built-in cache, per-request usage."""
import logging
import os
import time

import litellm

litellm.suppress_debug_info = True
# LiteLLM's built-in in-memory cache. Key = model + messages (+ sampling params); api_key is not part of it,
# so a reply produced by key_1 is a valid hit for any key.
litellm.cache = litellm.Cache(type="local")

log = logging.getLogger("llm")
TEMPERATURE = 0.3


class ProviderError(Exception):
    def __init__(self, status: int):
        super().__init__(f"simulated provider status {status}")
        self.status = status


class AllProvidersUnavailable(Exception):
    pass


def get_keys() -> list[str]:
    return [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]


def get_model() -> str:
    return os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash")


def parse_simulation(header: str | None) -> dict[str, int]:
    if not header or os.getenv("ENABLE_FAILURE_SIMULATION", "").lower() != "true":
        return {}
    out = {}
    for part in header.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            status = int(v.strip())
        except ValueError:
            continue
        if status in (429, 500, 502, 503):
            out[k.strip()] = status
    return out


async def _completion(model: str, messages: list[dict], api_key: str, bypass_cache: bool):
    kwargs = dict(model=model, messages=messages, api_key=api_key, temperature=TEMPERATURE,
                  caching=True, timeout=30, num_retries=0)
    if bypass_cache:
        kwargs["cache"] = {"no-cache": True}
    return await litellm.acompletion(**kwargs)


async def complete(messages: list[dict], simulate: dict[str, int]) -> tuple[str, dict]:
    keys, model = get_keys(), get_model()
    start = time.perf_counter()
    attempts = 0
    for i, key in enumerate(keys, 1):
        kid = f"key_{i}"
        try:
            status = simulate.get(kid) or simulate.get("*")
            if status:
                raise ProviderError(status)
            # When simulating, skip cache reads so the failover path is really exercised.
            resp = await _completion(model, messages, key, bypass_cache=bool(simulate))
            reply = (resp.choices[0].message.content or "").strip()
            if not reply:
                raise ValueError("empty completion")
        except Exception as e:  # 429, quota, 5xx, timeouts, auth, empty -> next key. Never log the key.
            attempts += 1
            log.warning("%s failed: %s", kid, type(e).__name__)
            continue
        hit = bool((getattr(resp, "_hidden_params", None) or {}).get("cache_hit"))
        usage = getattr(resp, "usage", None)
        meta = {
            "resolution_source": "LLM_CACHE" if hit else "LIVE_INFERENCE",
            "model": model,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "key_id": None if hit else kid,
            "fallback_attempts": 0 if hit else attempts,
        }
        return reply, meta
    raise AllProvidersUnavailable()
