# Verda Inference setup for the future DeepSeek rival

Verified against official Verda documentation on 2026-11-14. This is an
integration note, not an implemented provider adapter. No live request was made.

## Endpoint and model

- OpenAI-compatible base URL: `https://inference.verda.com/v1`
- Model ID: `deepseek-4-1-flash-1017`
- Supported APIs include `POST /v1/chat/completions`, `POST /v1/responses`, and
  `GET /v1/models`.
- Enable the model in Console under **Inference > Models** before calling it.

The Verda model ID is deliberately not replaced with the direct DeepSeek API alias.
At benchmark startup, query the Verda models endpoint and fail explicitly if the
configured model is unavailable rather than silently selecting another model.

## Credential setup

Enabling a model presents a new Inference API key once. A replacement can be
created from the model page or Credentials page. This key is distinct from Verda
Cloud API credentials and is sent as a bearer token.

Use environment variables only:

```sh
export VERDA_INFERENCE_BASE_URL=https://inference.verda.com
export VERDA_INFERENCE_API_KEY='...'
```

For an unmodified OpenAI client, the equivalent variables are:

```sh
export OPENAI_BASE_URL=https://inference.verda.com/v1
export OPENAI_API_KEY="$VERDA_INFERENCE_API_KEY"
```

Do not commit the key, place it in prompts, or persist it in runtime traces. Verda
associates inference keys with the team member who created them; removing that
member deletes their keys. Rotate a key immediately if it is exposed.

Minimal Python shape for the future adapter:

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://inference.verda.com/v1",
    api_key=os.environ["VERDA_INFERENCE_API_KEY"],
)
response = client.chat.completions.create(
    model="deepseek-4-1-flash-1017",
    messages=messages,
    max_tokens=max_tokens,
)
```

DeepSeek reasoning is controlled on Verda with `reasoning_effort` (`low`, `high`,
or `max`), not the provider-specific `thinking` field. Reasoning tokens are billed
as output tokens. Omit `reasoning_effort`, or use `none`, when reasoning is not
required.

## Billing and usage

Inference is prepaid from the Verda project balance. The project needs at least
USD 1 of balance to enable a model, and Verda documents a USD 20 minimum top-up.
Low balance pauses inference. Console is the source of truth:

- **Inference > Usage**: daily UTC input, cached-input, and output tokens by model;
  CSV export is available.
- **Billing > Billing history > Inference**: charged usage.
- The model page: current price, rate limits, and live availability.

The public price snapshot on 2026-11-14 for this model was, per one million tokens:

- input: USD 0.15
- cached input: USD 0.006
- output, including reasoning: USD 0.60

These rates are a dated estimate only. The account may use another billing
currency, and prices can change. Record a pricing snapshot date, currency, and
rates with each evaluation batch. Estimated request cost is:

```text
non_cached_input / 1e6 * input_rate
+ cached_input / 1e6 * cached_input_rate
+ output_including_reasoning / 1e6 * output_rate
```

Reconcile estimates with Verda Billing history. The response `usage` object is the
per-request token source. For streaming calls, request
`stream_options.include_usage=true`; usage then arrives in the final chunk.

Verda states that failed or interrupted requests, including timeouts, client
disconnects, and stopped streams, are not charged. The runtime should nevertheless
record status, request ID, latency, retries, returned model, service tier, token
categories, and the dated price snapshot. It must not retry a 402 balance error or
a 403 model-not-enabled error. For 429 responses, honor `Retry-After` within the
benchmark wall-clock budget.

## Operational checks before a benchmark

1. Confirm project balance and that the model is enabled.
2. Confirm `GET /v1/models` contains `deepseek-4-1-flash-1017`.
3. Run one minimal, separately labeled connectivity smoke request.
4. Check the returned `usage` fields and reconcile the request in Console.
5. Freeze model ID, sampling/reasoning settings, prompt hash, rate-limit policy,
   and price snapshot for the paired evaluation.

Do not use the Playground for a free test assumption: Verda bills Playground usage
the same way as API usage.

## Official references

- <https://docs.verda.com/inference/>
- <https://docs.verda.com/inference/quickstart/>
- <https://docs.verda.com/inference/models/>
- <https://docs.verda.com/inference/models/deepseek-4-1-flash-1017/>
- <https://docs.verda.com/inference/faq/>
- <https://docs.verda.com/welcome-to-verda/api-credentials/>
- <https://verda.com/models/deepseek-v4-1-flash>
