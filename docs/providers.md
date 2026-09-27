# Model providers

Every provider is reached through the same OpenAI-compatible client
(`thunorheim/llm.py`). What differs is captured in `models.toml`, per provider:

| Provider | Base URL | Allowed use | JSON mode | Stream usage |
|---|---|---|---|---|
| Gemini API (AI Studio) | `generativelanguage.googleapis.com/v1beta/openai/` | public (free tier) | `json_object` | yes |
| Groq | `api.groq.com/openai/v1` | public (free tier) | `json_object` | yes |
| NVIDIA API catalog | `integrate.api.nvidia.com/v1` | **dev only** | `json_object` | yes |

`THUNORHEIM_PROFILE=public` drops every `dev` provider from every role chain, so the
hosted demo can't reach one by accident.

## Why each row says what it says

- **NVIDIA — dev only.** The API Trial Terms of Service (§1) say: *"you may only use the
  API Service for internal testing and evaluation purposes, not in production."* Fine for
  development, the narrator bake-off and evals; never for the public demo.
  [Terms](https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf)
- **Gemini — free tier only.** Google Cloud trial credits *"can't pay for Gemini API in
  AI Studio costs"*; credit-billed Gemini would go through Vertex AI instead. The free
  tier may use inputs to improve Google's products, which the hosted demo must disclose.
  [Free trial terms](https://docs.cloud.google.com/free/docs/free-cloud-features)
- **Groq.** Free tier limits are per model and per account, not per provider
  (roughly 30 req/min and 1,000 req/day on the main models, September 2026). Groq
  retired Llama 3.1 8B and 3.3 70B on 2026-08-16, so models are config, never code.
  [Deprecations](https://console.groq.com/docs/deprecations)

## Limits that shape role assignment

- Groq's free tier allows ~8,000 tokens/minute on its main models. A Resolution prompt
  (rules + quest + lore) is larger than that, so Resolution is never Groq-first.
- NVIDIA doesn't publish its limits (commonly ~40 req/min); the gateway treats every
  429 as "move to the next provider".

## Verification

Capabilities above are checked with a live call per provider/model before a model is
added to a chain. Last checked 2026-09-27 (JSON call + streamed call, through the gateway):

| Model | JSON call | First token | Notes |
|---|---|---|---|
| groq `qwen/qwen3.8-27b` | 1.3 s | 0.07 s | route default |
| groq `openai/gpt-oss-120b` | 1.2 s | 0.35 s | narrate default |
| gemini `gemini-3.5-flash-lite` | 1.1 s | 0.7 s | fast fallback everywhere |
| gemini `gemini-3.5-flash` | ~10 s | — | resolve default; thinking model, slow |
| gemini `gemini-3.8-flash` | 4.3 s | — | 503 on repeated calls; not in defaults |
| gemini `gemini-2.5-*` | — | — | 404: retired for new keys |
| nvidia `nvidia/nemotron-3-super-120b-a12b` | 2.1 s | 4.4 s | dev fallback |
| nvidia `moonshotai/kimi-k3` | 6.6 s | — | streamed an empty reply; not in defaults |
| nvidia `z-ai/glm-5.3` | 53 s | 108 s | too slow |

Rerun the probe after changing `models.toml`; free-tier catalogs change without notice.
