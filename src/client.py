from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Project .env (one level up from src/), loaded regardless of the current working
# directory so background/cron runs pick up the key without a cd into the repo.
_ENV_PATH = Path(__file__).resolve().parents[1] / '.env'


def build_client() -> OpenAI:
    """Build an OpenAI-compatible client.

    Defaults to OpenRouter (https://openrouter.ai/api/v1). Set OPENROUTER_API_KEY
    (preferred) or OPENAI_API_KEY, and optionally OPENAI_BASE_URL to override the
    endpoint (e.g. https://api.openai.com/v1 for direct OpenAI).
    """
    # override=True so the project .env wins over a stale OPENROUTER_API_KEY that may
    # be exported in the shell profile (otherwise an old/empty key silently shadows it).
    load_dotenv(dotenv_path=str(_ENV_PATH) if _ENV_PATH.exists() else None, override=True)
    api_key = os.getenv('OPENROUTER_API_KEY') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError(
            'No API key found. Set OPENROUTER_API_KEY (or OPENAI_API_KEY) in the '
            'environment or a .env file.'
        )
    base_url = os.getenv('OPENAI_BASE_URL', 'https://openrouter.ai/api/v1')
    # Long full-day generations can be slow; give a generous timeout and several
    # automatic retries so a transient connection drop does not abort a run.
    return OpenAI(api_key=api_key, base_url=base_url, timeout=600.0, max_retries=5)


# Cap output length: a single stage (cards/narrative/JSON action list) fits well
# within this, but it stops the provider from reserving its full context for max
# output -- which both wastes budget headroom and trips OpenRouter's "can only
# afford N tokens" 402 pre-check. Override per call or via OPENROUTER_MAX_TOKENS.
DEFAULT_MAX_TOKENS = int(os.getenv('OPENROUTER_MAX_TOKENS', '16000'))

# Cumulative usage across every call_model call this process. Lets the pipeline/
# runner report how much prompt caching actually saved -- cached_tokens are billed
# at ~0.1x of normal input. Reset per run with reset_usage().
USAGE = {'calls': 0, 'prompt_tokens': 0, 'cached_tokens': 0,
         'completion_tokens': 0, 'cost': 0.0}


def reset_usage() -> None:
    USAGE.update(calls=0, prompt_tokens=0, cached_tokens=0, completion_tokens=0, cost=0.0)


def _accumulate(u: dict) -> None:
    USAGE['calls'] += 1
    USAGE['prompt_tokens'] += u.get('prompt_tokens') or 0
    USAGE['completion_tokens'] += u.get('completion_tokens') or 0
    USAGE['cost'] += u.get('cost') or 0.0
    USAGE['cached_tokens'] += (u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0


def call_model(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    response_format: dict | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    cache_prefix: str | None = None,
) -> str:
    """Single chat-completions call (OpenRouter-compatible).

    Pass response_format (e.g. a json_schema spec) to enforce structured output,
    and temperature (e.g. 0 for the deterministic judge) to control sampling.
    max_tokens defaults to DEFAULT_MAX_TOKENS (env OPENROUTER_MAX_TOKENS).

    cache_prefix, if given, is sent as a separate leading system block marked with
    Anthropic ``cache_control`` (ephemeral). It must be byte-identical across the
    calls that should share it; the first call writes the cache (~1.25x), every
    later call within the TTL reads it at ~0.1x. The stage-specific system_prompt
    follows it as an uncached block, so only the shared prefix is cached.
    """
    if cache_prefix:
        system_content: list | str = [
            {'type': 'text', 'text': cache_prefix, 'cache_control': {'type': 'ephemeral'}},
        ]
        if system_prompt:
            system_content.append({'type': 'text', 'text': system_prompt})
    else:
        system_content = system_prompt
    kwargs: dict = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_content},
            {'role': 'user', 'content': user_prompt},
        ],
        'max_tokens': max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
    }
    if response_format is not None:
        kwargs['response_format'] = response_format
    if temperature is not None:
        kwargs['temperature'] = temperature
    # with_raw_response so we can read OpenRouter's cache/cost usage fields, which
    # the typed SDK object does not expose.
    raw = client.chat.completions.with_raw_response.create(**kwargs)
    data = raw.http_response.json()
    _accumulate(data.get('usage') or {})
    choices = data.get('choices') or [{}]
    return ((choices[0].get('message') or {}).get('content') or '').strip()
