"""A tiny "support agent" that reports where its tokens, cost and time go.

By default it runs in FAKE mode: no API key, no internet, no cost. It simulates
LLM calls with realistic token counts and delays, so the Grafana graphs look real.

Optional REAL mode: set LLM_MODE=real plus LLM_BASE_URL, LLM_API_KEY and LLM_MODEL
for any OpenAI-compatible chat completions endpoint. Token counts then come from
the API response.

Endpoints
  GET /ask?q=...             run the agent on one question
  GET /chaos/runaway/on      make the agent loop on a failing tool (token spike)
  GET /chaos/runaway/off     back to normal
  GET /metrics               Prometheus scrape endpoint
"""
import logging
import os
import random
import time

import requests
from flask import Flask, Response, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")

MODE = os.environ.get("LLM_MODE", "fake").lower()

# Illustrative prices in USD per 1,000 tokens (not any vendor's real price list).
PRICES = {
    "model-large": {"input": 0.0025, "output": 0.0100},
    "model-mini": {"input": 0.00015, "output": 0.0006},
}

# Which model each agent step uses.
STEP_MODEL = {
    "plan": "model-mini",
    "tool_reasoning": "model-mini",
    "answer": "model-large",
    "retry": "model-large",
}

# ---------------------------------------------------------------- metrics
TOKENS = Counter(
    "agent_llm_tokens_total",
    "LLM tokens used, by model, token type (input/output) and agent step",
    ["model", "token_type", "step"],
)
COST = Counter(
    "agent_llm_cost_usd_total",
    "Estimated LLM cost in USD, by model and agent step",
    ["model", "step"],
)
LLM_CALLS = Counter(
    "agent_llm_calls_total",
    "Number of LLM calls, by model and agent step",
    ["model", "step"],
)
LLM_LATENCY = Histogram(
    "agent_llm_request_duration_seconds",
    "Latency of a single LLM call",
    ["model", "step"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8),
)
TOOL_CALLS = Counter(
    "agent_tool_calls_total",
    "Tool calls made by the agent, by tool and status",
    ["tool", "status"],
)
REQUESTS = Counter(
    "agent_requests_total",
    "Questions answered by the agent, by status",
    ["status"],
)
REQUEST_LATENCY = Histogram(
    "agent_request_duration_seconds",
    "End-to-end time to answer one question",
    buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32),
)
CALLS_PER_REQUEST = Histogram(
    "agent_llm_calls_per_request",
    "How many LLM calls one question needed",
    buckets=(1, 2, 3, 4, 5, 6, 8, 10, 15, 20),
)
RUNAWAY = Gauge("agent_runaway_mode", "1 while the runaway-agent incident is active")

state = {"runaway": False}

SYSTEM_PROMPT_TOKENS = 450  # every call re-sends the system prompt


# ---------------------------------------------------------------- LLM layer
def fake_llm(step, context_tokens):
    """Pretend to call a model; return (input_tokens, output_tokens)."""
    input_tokens = SYSTEM_PROMPT_TOKENS + context_tokens + random.randint(20, 80)
    output_tokens = {
        "plan": random.randint(40, 120),
        "tool_reasoning": random.randint(30, 90),
        "answer": random.randint(150, 400),
        "retry": random.randint(80, 200),
    }[step]
    # Bigger models and longer outputs take longer.
    per_token = 0.0006 if STEP_MODEL[step] == "model-large" else 0.0002
    time.sleep(0.03 + output_tokens * per_token + random.uniform(0, 0.05))
    return input_tokens, output_tokens


def real_llm(step, prompt):
    """Call an OpenAI-compatible endpoint and read token usage from the response."""
    resp = requests.post(
        os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + os.environ["LLM_API_KEY"]},
        json={
            "model": os.environ["LLM_MODEL"],
            "messages": [
                {"role": "system", "content": "You are a concise support agent. Step: " + step},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 200,
        },
        timeout=60,
    )
    resp.raise_for_status()
    usage = resp.json().get("usage", {})
    return usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def call_llm(step, context_tokens, prompt):
    model = STEP_MODEL[step]
    start = time.time()
    if MODE == "real":
        input_tokens, output_tokens = real_llm(step, prompt)
    else:
        input_tokens, output_tokens = fake_llm(step, context_tokens)
    LLM_LATENCY.labels(model, step).observe(time.time() - start)
    LLM_CALLS.labels(model, step).inc()
    TOKENS.labels(model, "input", step).inc(input_tokens)
    TOKENS.labels(model, "output", step).inc(output_tokens)
    price = PRICES[model]
    COST.labels(model, step).inc(
        input_tokens / 1000 * price["input"] + output_tokens / 1000 * price["output"]
    )
    return input_tokens, output_tokens


# ---------------------------------------------------------------- tools
def run_tool(name):
    time.sleep(random.uniform(0.02, 0.1))
    failing = state["runaway"] and name == "search_docs"
    status = "error" if failing or random.random() < 0.02 else "ok"
    TOOL_CALLS.labels(name, status).inc()
    return status, random.randint(150, 600)  # tokens of tool output added to context


def choose_tools(question):
    q = question.lower()
    tools = ["search_docs"]
    if "order" in q or "refund" in q:
        tools.append("lookup_order")
    if "price" in q or "total" in q or "discount" in q:
        tools.append("calculator")
    return tools


# ---------------------------------------------------------------- agent loop
def run_agent(question):
    calls = 0
    context = len(question.split()) * 2

    # 1. Plan which tools to use.
    i, o = call_llm("plan", context, question)
    calls += 1
    context += o

    # 2. Call each tool, reason about its output.
    for tool in choose_tools(question):
        status, tool_tokens = run_tool(tool)
        context += tool_tokens
        retries = 0
        # Runaway incident: the agent keeps retrying a failing tool, and the
        # context (and so the input tokens) grows on every attempt.
        while status == "error" and retries < (8 if state["runaway"] else 1):
            i, o = call_llm("retry", context, question)
            calls += 1
            context += o
            status, tool_tokens = run_tool(tool)
            context += tool_tokens
            retries += 1
        i, o = call_llm("tool_reasoning", context, question)
        calls += 1
        context += o

    # 3. Write the final answer.
    call_llm("answer", context, question)
    calls += 1
    CALLS_PER_REQUEST.observe(calls)
    return calls, context


@app.route("/")
def index():
    return jsonify(service="token-agent", mode=MODE, runaway=state["runaway"])


@app.route("/ask")
def ask():
    question = request.args.get("q", "How do I reset my password?")
    start = time.time()
    try:
        calls, context = run_agent(question)
        REQUESTS.labels("ok").inc()
        return jsonify(question=question, llm_calls=calls, final_context_tokens=context)
    except Exception as exc:  # noqa: BLE001 - keep the demo running
        REQUESTS.labels("error").inc()
        log.error("agent failed: %s", exc)
        return jsonify(error=str(exc)), 500
    finally:
        REQUEST_LATENCY.observe(time.time() - start)


@app.route("/chaos/runaway/on")
def runaway_on():
    state["runaway"] = True
    RUNAWAY.set(1)
    log.warning("runaway mode ON: search_docs now fails and the agent retries")
    return jsonify(runaway=True)


@app.route("/chaos/runaway/off")
def runaway_off():
    state["runaway"] = False
    RUNAWAY.set(0)
    log.warning("runaway mode OFF")
    return jsonify(runaway=False)


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
