"""The model gateway, driven through the real OpenAI client with a scripted HTTP
transport: failover, validation retries, streaming resets, record/replay."""

import asyncio
import json

import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError

from thunorheim import llm

CONFIG = {
    "providers": {
        "a": {
            "base_url": "https://a.test/v1",
            "key_env": "A_KEY",
            "use": "public",
            "json": "object",
        },
        "b": {"base_url": "https://b.test/v1", "key_env": "B_KEY", "use": "dev", "json": "none"},
    },
    "roles": {"x": ["a:model-a", "b:model-b"]},
}


class Out(BaseModel):
    n: int


class Script:
    """Per-host queue of canned responses (or exceptions); records every request."""

    def __init__(self):
        self.queue: dict[str, list] = {}
        self.requests: list[httpx.Request] = []

    def add(self, host, *items):
        self.queue.setdefault(host, []).extend(items)

    def __call__(self, request):
        self.requests.append(request)
        item = self.queue[request.url.host].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def body(self, i):
        return json.loads(self.requests[i].content)


def completion(content, usage=(12, 5)):
    return httpx.Response(
        200,
        json={
            "id": "c",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": usage[0],
                "completion_tokens": usage[1],
                "total_tokens": sum(usage),
            },
        },
    )


def chunk(text):
    body = {
        "id": "c",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    return f"data: {json.dumps(body)}\n\n"


def sse(*texts):
    body = "".join(map(chunk, texts)) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


class DropsMidStream(httpx.AsyncByteStream):
    def __init__(self, *texts):
        self.texts = texts

    async def __aiter__(self):
        for text in self.texts:
            yield chunk(text).encode()
        raise httpx.ReadError("connection reset")


def error(status):
    return httpx.Response(status, json={"error": {"message": f"status {status}"}})


@pytest.fixture
def script(monkeypatch):
    monkeypatch.setenv("A_KEY", "secret-a")
    monkeypatch.setenv("B_KEY", "secret-b")
    monkeypatch.setattr(llm, "_backoff", lambda attempt: 0)
    script = Script()
    llm.configure(config=CONFIG, transport=httpx.MockTransport(script))
    yield script
    llm.configure()


def traced(make_call):
    """Run one gateway call inside a trace; return (result, spans)."""

    async def main():
        spans = llm.start_trace()
        return await make_call(), spans

    return asyncio.run(main())


def structured():
    return llm.structured("x", Out, "system", "user", prompt="t@1")


# --- structured output -----------------------------------------------------------------


def test_structured_output_is_parsed_and_traced(script):
    script.add("a.test", completion('{"n": 3}'))
    out, [span] = traced(structured)
    assert out.n == 3
    assert (span.provider, span.model, span.prompt, span.ok) == ("a", "model-a", "t@1", True)
    assert (span.tokens_in, span.tokens_out, span.retries) == (12, 5, 0)
    assert script.body(0)["response_format"] == {"type": "json_object"}


def test_invalid_output_is_retried_with_the_error_fed_back(script):
    script.add("a.test", completion("not json at all"), completion('```json\n{"n": 4}\n```'))
    out, _ = traced(structured)
    assert out.n == 4
    assert "failed validation" in script.body(1)["messages"][-1]["content"]


def test_output_invalid_twice_fails_the_call(script):
    script.add("a.test", completion('{"n": "many"}'), completion('{"n": "lots"}'))
    with pytest.raises(ValidationError):
        traced(structured)


# --- failover ---------------------------------------------------------------------------


def test_a_rate_limit_fails_over_to_the_next_provider(script):
    script.add("a.test", error(429))
    script.add("b.test", completion('{"n": 1}'))
    out, [span] = traced(structured)
    assert out.n == 1
    assert (span.provider, span.errors) == ("b", ["a: 429"])
    assert "response_format" not in script.body(1)  # provider b is prompt-only JSON


def test_a_transient_error_retries_the_same_provider_once(script):
    script.add("a.test", error(503), completion('{"n": 2}'))
    _, [span] = traced(structured)
    assert (span.provider, span.retries) == ("a", 1)


def test_when_every_provider_fails_the_call_fails(script):
    script.add("a.test", error(429))
    script.add("b.test", error(500), httpx.ReadTimeout("slow"))
    with pytest.raises(llm.AllProvidersFailed):
        traced(structured)


def test_the_public_profile_never_touches_dev_only_providers(script):
    llm.configure(config=CONFIG, profile="public", transport=httpx.MockTransport(script))
    script.add("a.test", error(429))
    with pytest.raises(llm.AllProvidersFailed):
        traced(structured)
    assert {r.url.host for r in script.requests} == {"a.test"}


def test_no_configured_keys_is_a_clear_error(script, monkeypatch):
    monkeypatch.delenv("A_KEY")
    monkeypatch.delenv("B_KEY")
    with pytest.raises(llm.AllProvidersFailed, match="API keys"):
        traced(structured)


# --- streaming -------------------------------------------------------------------------


def stream_all():
    async def call():
        return [c async for c in llm.stream("x", "system", "user", prompt="t@1")]

    return call


def test_a_stream_yields_deltas_and_time_to_first_token(script):
    script.add("a.test", sse("The wind ", "turns."))
    chunks, [span] = traced(stream_all())
    assert chunks == ["The wind ", "turns."]
    assert span.ok and span.ttft_ms is not None


def test_a_dropped_stream_resets_instead_of_splicing(script):
    dropped = httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=DropsMidStream("The door ")
    )
    script.add("a.test", dropped)
    script.add("b.test", sse("A wolf ", "howls."))
    chunks, [span] = traced(stream_all())
    assert chunks == ["The door ", llm.RESET, "A wolf ", "howls."]
    assert span.provider == "b"

    async def final():
        return await llm.collect(_aiter(chunks))

    assert asyncio.run(final()) == "A wolf howls."


async def _aiter(items):
    for item in items:
        yield item


# --- record / replay ----------------------------------------------------------------------


def test_a_recording_replays_without_keys_or_network(script, tmp_path, monkeypatch):
    cassette = tmp_path / "turns.jsonl"
    llm.configure(config=CONFIG, transport=httpx.MockTransport(script), record=cassette)
    script.add("a.test", completion('{"n": 7}'))
    recorded, _ = traced(structured)

    saved = cassette.read_text()
    assert "secret-a" not in saved and "authorization" not in saved.lower()

    monkeypatch.delenv("A_KEY")
    monkeypatch.delenv("B_KEY")
    llm.configure(config=CONFIG, replay=cassette)
    replayed, _ = traced(structured)
    assert replayed == recorded
    assert len(script.requests) == 1  # replay never reached the network


def test_a_replay_miss_fails_fast_and_says_why(script, tmp_path):
    llm.configure(config=CONFIG, replay=tmp_path / "empty.jsonl")
    with pytest.raises(openai.NotFoundError, match="no recording"):
        traced(structured)
