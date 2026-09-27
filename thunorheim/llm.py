"""Model gateway.

Every provider speaks the OpenAI chat-completions API, so one client type covers
them all; `models.toml` says which model plays which role and in what failover
order. On top of that client this module adds:

* failover — 429 moves to the next provider; timeouts/5xx retry once, then move on
* validated output — `structured()` parses into a Pydantic schema and, if the reply
  doesn't fit, retries once with the validation error fed back
* streaming — `stream()` fails over mid-stream by yielding RESET and restarting on
  the next provider; two models' prose is never spliced together
* tracing — one Span per call (provider, model, prompt version, latency, time to
  first token, tokens, retries, errors), collected per turn via `start_trace()`
* record/replay — a cassette at the HTTP layer keyed by (host, request body); the
  body holds model + messages but never credentials, so recordings are safe to commit
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import random
import time
import tomllib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import openai
from dotenv import load_dotenv
from openai import AsyncOpenAI, Omit, omit
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionStreamOptionsParam
from openai.types.chat.completion_create_params import ResponseFormat
from pydantic import BaseModel, ValidationError

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = httpx.Timeout(60.0, connect=10.0)
TRANSIENT = (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)


class Reset:
    """Yielded by stream() when a provider died mid-reply: discard what you have."""


RESET = Reset()


class AllProvidersFailed(RuntimeError):
    pass


# --- tracing -----------------------------------------------------------------------


@dataclass
class Span:
    role: str
    prompt: str
    provider: str = ""
    model: str = ""
    ms: int = 0
    ttft_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    retries: int = 0
    errors: list[str] = field(default_factory=list)
    ok: bool = False


_trace: contextvars.ContextVar[list[Span] | None] = contextvars.ContextVar("trace", default=None)


def start_trace() -> list[Span]:
    """Collect a Span for every model call made from the current task onward."""
    spans: list[Span] = []
    _trace.set(spans)
    return spans


def _finish(span: Span, t0: float) -> None:
    span.ms = round((time.perf_counter() - t0) * 1000)
    spans = _trace.get()
    if spans is not None:
        spans.append(span)


# --- record / replay ------------------------------------------------------------


@cache
def _recordings(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    return {e["key"]: e for e in map(json.loads, filter(None, lines))}


class Cassette(httpx.AsyncBaseTransport):
    """Replays recorded model traffic; in record mode, forwards and saves it."""

    def __init__(
        self, path: Path, *, record: bool, inner: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.path = path
        self.record = record
        self.inner = inner or httpx.AsyncHTTPTransport()
        self.entries = _recordings(path)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = hashlib.sha256(request.url.host.encode() + request.content).hexdigest()[:20]
        if not self.record:
            entry = self.entries.get(key)
            if entry is None:
                # a 404, not an exception: the client would wrap an exception as a
                # connection error, and the gateway would retry it as a blip
                message = f"no recording {key} in {self.path}; re-record the scenario"
                return httpx.Response(404, json={"error": {"message": message}})
            return self._response(entry)
        response = await self.inner.handle_async_request(request)
        body = (await response.aread()).decode()
        entry = {
            "key": key,
            "status": response.status_code,
            "type": response.headers.get("content-type", ""),
            "body": body,
        }
        self.entries[key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return self._response(entry)  # record and replay hand the client the same thing

    @staticmethod
    def _response(entry: dict[str, Any]) -> httpx.Response:
        # The body is stored decoded, so only the content type goes back; echoing the
        # provider's content-encoding would make the client gunzip plain text.
        headers = {"content-type": entry["type"]}
        return httpx.Response(entry["status"], headers=headers, content=entry["body"])


# --- configuration -----------------------------------------------------------------


@dataclass(frozen=True)
class Provider:
    name: str
    client: AsyncOpenAI
    use: str
    json: str
    stream_usage: bool


@dataclass
class _Settings:
    config: dict[str, Any] | None = None
    profile: str | None = None
    transport: httpx.AsyncBaseTransport | None = None
    replay: Path | None = None
    record: Path | None = None


_settings = _Settings()
_built: tuple[asyncio.AbstractEventLoop, dict[str, Provider]] | None = None


def configure(
    *,
    config: dict[str, Any] | None = None,
    profile: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    replay: Path | None = None,
    record: Path | None = None,
) -> None:
    """Override env/file settings (tests, evals). Call with no args to reset."""
    global _settings, _built
    _settings = _Settings(config, profile, transport, replay, record)
    _built = None


def _config() -> dict[str, Any]:
    if _settings.config is not None:
        return _settings.config
    path = Path(os.environ.get("THUNORHEIM_MODELS", ROOT / "models.toml"))
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _profile() -> str:
    return _settings.profile or os.environ.get("THUNORHEIM_PROFILE", "dev")


def _env_path(value: Path | None, env: str) -> Path | None:
    raw = value or os.environ.get(env)
    return Path(raw) if raw else None


def _providers() -> dict[str, Provider]:
    # ponytail: clients are rebuilt per event loop because the sync UIs call
    # asyncio.run() per turn and httpx pools are loop-bound. A long-lived loop
    # (the API server) builds them once.
    global _built
    loop = asyncio.get_running_loop()
    if _built is not None and _built[0] is loop:
        return _built[1]

    replay = _env_path(_settings.replay, "THUNORHEIM_REPLAY")
    record = _env_path(_settings.record, "THUNORHEIM_RECORD")
    transport = _settings.transport
    if replay or record:
        transport = Cassette(replay or record, record=bool(record), inner=transport)  # type: ignore[arg-type]

    providers = {}
    for name, spec in _config()["providers"].items():
        key = os.environ.get(spec["key_env"]) or ("replay" if replay else None)
        if not key:
            continue  # not configured on this machine; chains skip it
        http = httpx.AsyncClient(transport=transport, timeout=TIMEOUT) if transport else None
        client = AsyncOpenAI(
            base_url=spec["base_url"], api_key=key, max_retries=0, timeout=TIMEOUT, http_client=http
        )
        providers[name] = Provider(
            name, client, spec["use"], spec.get("json", "none"), spec.get("stream_usage", False)
        )
    _built = (loop, providers)
    return providers


def _chain(role: str) -> list[tuple[Provider, str]]:
    providers = _providers()
    public_only = _profile() == "public"
    chain = []
    for entry in _config()["roles"][role]:
        name, model = entry.split(":", 1)
        provider = providers.get(name)
        if provider and (provider.use == "public" or not public_only):
            chain.append((provider, model))
    if not chain:
        raise AllProvidersFailed(
            f"no usable provider for role {role!r} (profile={_profile()}); check API keys in .env"
        )
    return chain


def _backoff(attempt: int) -> float:
    return 0.5 * 2.0**attempt * random.uniform(0.5, 1.5)


# --- calls ---------------------------------------------------------------------------


async def _complete(
    role: str, messages: list[ChatCompletionMessageParam], prompt: str, want_json: bool = False
) -> str:
    span, t0 = Span(role, prompt), time.perf_counter()
    try:
        for provider, model in _chain(role):
            fmt: ResponseFormat | Omit = omit
            if want_json and provider.json == "object":
                fmt = {"type": "json_object"}
            for attempt in range(2):
                try:
                    resp = await provider.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_format=fmt,
                    )
                except openai.RateLimitError:
                    span.errors.append(f"{provider.name}: 429")
                    break  # quota, not a blip: next provider
                except TRANSIENT as err:
                    span.errors.append(f"{provider.name}: {type(err).__name__}")
                    if attempt == 0:
                        span.retries += 1
                        await asyncio.sleep(_backoff(attempt))
                    continue
                content = resp.choices[0].message.content if resp.choices else None
                if not content:
                    # thinking models can spend the whole reply on hidden reasoning
                    span.errors.append(f"{provider.name}: empty reply")
                    break
                span.provider, span.model, span.ok = provider.name, model, True
                if resp.usage:
                    span.tokens_in = resp.usage.prompt_tokens
                    span.tokens_out = resp.usage.completion_tokens
                return content
        raise AllProvidersFailed(f"{role}: {'; '.join(span.errors)}")
    finally:
        _finish(span, t0)


def _messages(system: str, user: str) -> list[ChatCompletionMessageParam]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _json_body(raw: str) -> str:
    """Tolerate prose or code fences around the JSON object."""
    start, end = raw.find("{"), raw.rfind("}")
    return raw[start : end + 1] if start != -1 and end > start else raw


async def structured[T: BaseModel](
    role: str, schema: type[T], system: str, user: str, *, prompt: str
) -> T:
    """One model call parsed into `schema`; one retry with the validation error fed back."""
    messages = _messages(system, user)
    raw = await _complete(role, messages, prompt, want_json=True)
    try:
        return schema.model_validate_json(_json_body(raw))
    except ValidationError as err:
        problems = "\n".join(f"- {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in err.errors())
        messages += [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": f"That JSON failed validation:\n{problems}\n"
                "Return the corrected JSON object only.",
            },
        ]
        raw = await _complete(role, messages, prompt, want_json=True)
        return schema.model_validate_json(_json_body(raw))


async def text(role: str, system: str, user: str, *, prompt: str) -> str:
    messages = _messages(system, user)
    return (await _complete(role, messages, prompt)).strip()


async def stream(role: str, system: str, user: str, *, prompt: str) -> AsyncIterator[str | Reset]:
    """Yield text deltas. If a provider dies mid-reply, yield RESET and restart on the
    next one."""
    messages = _messages(system, user)
    span, t0 = Span(role, prompt), time.perf_counter()
    try:
        for provider, model in _chain(role):
            started = False
            usage: ChatCompletionStreamOptionsParam | Omit = omit
            if provider.stream_usage:
                usage = {"include_usage": True}
            try:
                resp = await provider.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                    stream_options=usage,
                )
                async for chunk in resp:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        if not started:
                            span.ttft_ms = round((time.perf_counter() - t0) * 1000)
                            started = True
                        yield delta
                    if chunk.usage:
                        span.tokens_in = chunk.usage.prompt_tokens
                        span.tokens_out = chunk.usage.completion_tokens
            except (openai.RateLimitError, *TRANSIENT, httpx.HTTPError) as err:
                # ponytail: streams fail over without a same-provider retry
                span.errors.append(f"{provider.name}: {type(err).__name__}")
                if started:
                    yield RESET
                continue
            if not started:
                span.errors.append(f"{provider.name}: empty reply")
                continue
            span.provider, span.model, span.ok = provider.name, model, True
            return
        raise AllProvidersFailed(f"{role}: {'; '.join(span.errors)}")
    finally:
        _finish(span, t0)


async def collect(chunks: AsyncIterator[str | Reset]) -> str:
    """Drain a stream into its final text, honoring RESET."""
    parts: list[str] = []
    async for chunk in chunks:
        if isinstance(chunk, Reset):
            parts.clear()
        else:
            parts.append(chunk)
    return "".join(parts).strip()
