# Context for GitHub Copilot

This repo is a local lab for observing an LLM agent: a Python "support agent", Prometheus and Grafana, run with Docker Compose.

## Metrics the agent exposes (use these exact names)

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `agent_llm_tokens_total` | counter | `model`, `token_type` (`input`/`output`), `step` | Tokens used by LLM calls |
| `agent_llm_cost_usd_total` | counter | `model`, `step` | Estimated cost in USD |
| `agent_llm_calls_total` | counter | `model`, `step` | Number of LLM calls |
| `agent_llm_request_duration_seconds` | histogram | `model`, `step` | Latency of one LLM call |
| `agent_tool_calls_total` | counter | `tool`, `status` (`ok`/`error`) | Tool calls |
| `agent_requests_total` | counter | `status` | Questions answered |
| `agent_request_duration_seconds` | histogram | none | End-to-end time per question |
| `agent_llm_calls_per_request` | histogram | none | LLM calls needed per question |
| `agent_runaway_mode` | gauge | none | 1 while the runaway incident is on |

Label values:
- `model`: `model-large`, `model-mini`
- `step`: `plan`, `tool_reasoning`, `answer`, `retry`
- `tool`: `search_docs`, `lookup_order`, `calculator`

## Conventions

- Prometheus scrapes every 5s. Use `[1m]` windows for rates and `[5m]` for percentiles and per-request averages.
- Counters always go through `rate()` or `increase()`; never graph a raw counter.
- Percentiles: `histogram_quantile(0.95, sum by (le) (rate(<metric>_bucket[5m])))`; always keep `le` in the `by` clause.
- Tokens per question: `sum(rate(agent_llm_tokens_total[5m])) / sum(rate(agent_requests_total[5m]))`.
- Cost per hour: `sum(rate(agent_llm_cost_usd_total[5m])) * 3600`.
- Grafana Prometheus datasource uid is `prometheus`.
- Dashboard JSON goes in `grafana/dashboards/` (Grafana reloads it every 10s). Use a fixed `uid`, `"id": null`, and `schemaVersion` 39 or later.
- When writing a query, explain it in one line and say how to verify it.
