# MCP Integration Guide

This guide shows how to plug `aware-ai` into an MCP-compatible tool ecosystem without removing the guardrail layer. The design is intentionally small and production-minded: the agent can route work to external tools, but every tool call still passes through the same validation, risk checks, and observability controls used elsewhere in the system.

## Why this matters

A typical AI workflow fails in one of two ways:

- tools are exposed without safety checks, which creates prompt injection and data leakage risk
- tools are added, but no one can explain how they fit into the application architecture

`aware-ai` solves both by keeping tool execution behind a structured gateway. The flow is:

1. receive a user request
2. select a route / agent
3. determine whether a tool is needed
4. validate tool parameters and policy requirements
5. execute the tool through the MCP server layer
6. pass the result back through guardrails before final response generation

This keeps the system explainable and auditable.

## Recommended integration pattern

```text
Client Request
      ↓
Gateway / Inference Router
      ↓
Agent Selection
      ↓
MCP Tool Resolver
      ↓
Guardrail Validation
      ↓
Tool Execution (filesystem, fetch, git, memory, etc.)
      ↓
Response Normalization
      ↓
Final Safety Check
      ↓
User Response
```

## Example: Guardrailed MCP call

The following example shows a simple pattern for routing a task through an MCP-backed fetch tool while preserving the guardrail pipeline:

```python
from apps.gateway import create_app
from apps.orchestrator import get_orchestrator
from libs.guardrail import SafeInferenceV3

guardrails = SafeInferenceV3(
    pii_detection=True,
    prompt_injection_detection=True,
    toxicity_detection=True,
    max_output_tokens=1200,
)

async def run_mcp_task():
    orchestrator = await get_orchestrator()

    result = await orchestrator.run(
        agent_id="coding",
        prompt="Fetch the release notes for the latest MCP server and summarize the key changes.",
        tools=["mcp_fetch"],
        guardrails=guardrails,
        metadata={
            "source": "mcp-guided-research",
            "privacy_level": "INTERNAL",
        },
    )

    return result
```

This pattern is useful when you want the model to access an MCP server such as:

- `fetch` for web retrieval
- `filesystem` for controlled file access
- `git` for repository inspection
- `memory` for persistent context

## Example: local MCP + Aware.ai lifecycle

```bash
# 1. Start the core services
./start.sh

# 2. Start an MCP server locally (example)
uvx mcp-server-fetch

# 3. Call the Aware.ai gateway with a tool-aware prompt
curl -X POST http://localhost:8000/v1/inference \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Use the fetch tool to summarize the official MCP documentation for a developer audience.",
    "agent_id": "default",
    "stream": false,
    "constraints": {
      "max_latency_ms": 30000,
      "privacy_level": "INTERNAL"
    }
  }'
```

## Security notes

When connecting to MCP tools, keep these rules in mind:

- restrict filesystem access to explicit allowlists
- validate URLs before fetch requests
- treat external content as untrusted input
- run post-generation checks for leakage, toxicity, and prompt injection
- keep a request audit trail for all tool invocations

## Suggested production pattern

For a production deployment, use a simple policy like this:

- `fetch` is allowed only for approved domains
- `filesystem` is restricted to a designated workspace
- `git` is read-only unless explicitly approved
- `memory` is scoped to user session state, not global shared memory

This ensures the MCP tool layer remains useful without becoming a security loophole.

## Summary

`aware-ai` works naturally as the guardrailed orchestration layer in front of MCP servers. The integration is not about replacing MCP; it is about giving MCP tools a safer, more observable, and more production-ready execution path.

This keeps your multi-agent system aligned with the same principles you already emphasize in the project: local-first control, safety, privacy, and resilience.
