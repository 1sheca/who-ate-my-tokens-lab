# Who Ate My Tokens? Observing LLM Agents with Grafana and the GitHub Copilot CLI

A hands-on lab. You run a small "support agent" that reports its token usage, cost and latency to Prometheus, then use the **GitHub Copilot CLI** in your terminal to write the queries and build the Grafana dashboard that shows where the tokens go.

No API key needed: the agent runs in **fake LLM mode** by default (realistic token counts, zero cost, works offline).

---

## Option A: on your laptop (recommended)

### Before the session (about 15 minutes)

1. Install **Docker Desktop**, **Node.js 22+** and **Git**.
2. Install the GitHub Copilot CLI (pick one):
   - `npm install -g @github/copilot`
   - Windows: `winget install GitHub.Copilot`
   - macOS / Linux: `brew install --cask copilot-cli`
3. Sign in: run `copilot`, type `/login`, follow the browser prompt. A personal GitHub account with **Copilot Free** is enough.
4. Get this repo and download everything in advance (venue Wi-Fi is slow):
   ```bash
   git clone <repo-url> who-ate-my-tokens-lab
   cd who-ate-my-tokens-lab
   docker compose --profile mcp pull
   docker compose build
   ```

### Start the lab

```bash
docker compose up -d
```

| What | URL | Notes |
| --- | --- | --- |
| Agent | http://localhost:8080 | `/ask?q=...` runs the agent once |
| Prometheus | http://localhost:9090 | `/targets` should show `token-agent` **UP** |
| Grafana | http://localhost:3000 | login `admin` / `admin` |
| Grafana MCP server (Lab 3) | http://localhost:8000/mcp | start with `docker compose --profile mcp up -d` |

## Option B: no Docker? Use GitHub Codespaces

On this repo's GitHub page: **Code > Codespaces > Create codespace**. The container installs Docker and the Copilot CLI for you. Then run `docker compose up -d` in its terminal and open port 3000 from the **Ports** tab. Personal GitHub accounts include free Codespaces hours each month.

---

## Lab 1: Ask your agent's metrics

In the lab folder:

```bash
copilot -sp "Write a PromQL query for tokens per question for the agent"
```

Paste the query into **Grafana > Explore > Prometheus** and run it. Then, inside `copilot`:

> Write PromQL for: tokens per second by agent step, cost per hour in USD, and p95 time per question. Then run each one against http://localhost:9090/api/v1/query with curl and summarise the results.

## Lab 2: Token dashboard as code

Inside `copilot`:

> Create grafana/dashboards/tokens.json: a Grafana dashboard titled "Who Ate My Tokens?", uid "tokens", Prometheus datasource uid "prometheus". Panels: stat for tokens per question, stat for cost per hour, time series of tokens per second by step, bar gauge of cost by step over the selected time range, time series of tool calls by tool and status. Refresh 5s, last 15 minutes.

Open **Grafana > Dashboards > Workshop** within ~10 seconds. Fell behind? `cp checkpoints/token-dashboard.json grafana/dashboards/`

## Lab 3: Catch a runaway agent (demo)

```bash
docker compose --profile mcp up -d
```

In `copilot`: run `/mcp add`, name `grafana`, type **HTTP**, URL `http://localhost:8000/mcp`, tools `*`, then **Ctrl+S**. Check with `/mcp show grafana`.

Break the agent: `curl http://localhost:8080/chaos/runaway/on`, wait about a minute, then ask:

> Using the Grafana tools, look at the token agent's metrics for the last 10 minutes. Why did tokens and cost jump, which step and tool are responsible, and what should I fix?

Fix it: `curl http://localhost:8080/chaos/runaway/off`

---

## Metrics reference

| Metric | Type | Labels |
| --- | --- | --- |
| `agent_llm_tokens_total` | counter | `model`, `token_type`, `step` |
| `agent_llm_cost_usd_total` | counter | `model`, `step` |
| `agent_llm_calls_total` | counter | `model`, `step` |
| `agent_llm_request_duration_seconds` | histogram | `model`, `step` |
| `agent_tool_calls_total` | counter | `tool`, `status` |
| `agent_requests_total` | counter | `status` |
| `agent_request_duration_seconds` | histogram | none |
| `agent_llm_calls_per_request` | histogram | none |
| `agent_runaway_mode` | gauge | none |

Prices in the agent are illustrative, not any vendor's real price list.

## Optional: real model mode

The agent works with any OpenAI-compatible chat completions endpoint. Token counts then come from the real API response. Slow the load generator down so you stay inside free-tier rate limits.

**GitHub Models (free tier for personal accounts, rate-limited).** Create a fine-grained personal access token with the `models:read` permission, then:

```bash
LLM_MODE=real \
LLM_BASE_URL=https://models.github.ai/inference \
LLM_API_KEY=<your-token> \
LLM_MODEL=openai/gpt-4o-mini \
INTERVAL_SECONDS=20 \
docker compose up -d --build agent loadgen
```

**Ollama (free, local, offline after the model download).** Install Ollama, run `ollama pull llama3.2:1b`, then:

```bash
LLM_MODE=real \
LLM_BASE_URL=http://host.docker.internal:11434/v1 \
LLM_API_KEY=ollama \
LLM_MODEL=llama3.2:1b \
INTERVAL_SECONDS=5 \
docker compose up -d --build agent loadgen
```

(On Linux, `host.docker.internal` may need `extra_hosts: ["host.docker.internal:host-gateway"]` on the agent service.)

Notes: the `model` label stays `model-large` / `model-mini` (the agent's step roles), and the cost uses the lab's illustrative prices. Never commit your token.

## Clean up

```bash
docker compose --profile mcp down
```
