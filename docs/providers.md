# Model providers

Every provider is reached through the same OpenAI-compatible client
(`thunorheim/llm.py`). What differs is captured in `models.toml`, per provider:

| Provider | Base URL | Allowed use | JSON mode | Stream usage |
|---|---|---|---|---|
| Gemini API (AI Studio) | `generativelanguage.googleapis.com/v1beta/openai/` | public (free tier) | `json_object` | yes |
| Groq | `api.groq.com/openai/v1` | public (free tier) | `json_object` | yes |
| NVIDIA API catalog | `integrate.api.nvidia.com/v1` | **dev only** | prompt-only | no |

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
added to a public chain. Last checked: pending first live run.
