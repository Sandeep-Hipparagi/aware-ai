# Aware.ai (BluePatterns AI) — Dual-Plane Adaptive Multi-Agent & Guardrail System

Local-first AI inference routing with privacy-preserving guardrails.

## Architecture

```
Client → Gateway → Orchestrator → Guardrail → Ollama (Local) → Guardrail → Client
                ↓
            Redis (State/Checkpoints/Streaming)
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- NVIDIA GPU (optional, for GPU acceleration)
- 16GB+ RAM recommended

### Start Services

**Linux/macOS:**
```bash
chmod +x start.sh
./start.sh
```

**Windows (PowerShell):**
```powershell
.\start.ps1
```

### Run Tests
```bash
pip install -r requirements.txt
python test_e2e.py
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |
| GET | `/health/ready` | Readiness check (dependencies) |
| GET | `/v1/agents` | List available agents |
| POST | `/v1/inference` | Run inference (streaming or non-streaming) |

### Inference Request
```json
{
  "prompt": "Write a Python fibonacci function",
  "agent_id": "coding",
  "stream": true,
  "constraints": {
    "max_latency_ms": 30000,
    "privacy_level": "INTERNAL"
  }
}
```

### Streaming Response (SSE)
```
data: {"request_id": "...", "content": "def ", "finish_reason": null, "is_final": false}
data: {"request_id": "...", "content": "fibonacci", "finish_reason": null, "is_final": false}
...
data: {"request_id": "...", "content": "", "finish_reason": "stop", "is_final": true}
data: [DONE]
```

## Available Agents

| Agent | Model | Use Case |
|-------|-------|----------|
| `default` | llama3.1:8b | General chat |
| `coding` | codellama:13b | Code generation |
| `reasoning` | llama3.1:8b | Complex reasoning |

## Guardrails (SafeInferenceV3)

- **Pre-flight**: PII detection, prompt injection, toxicity, length limits
- **Post-generation**: PII leakage, hallucination detection, toxicity

## Project Structure

```
.
├── apps/
│   ├── gateway/          # FastAPI ingress + SSE streaming
│   └── orchestrator/     # DAG execution + Redis state
├── libs/
│   ├── shared/           # Pydantic schemas
│   ├── ollama/           # Local Ollama client
│   ├── redis_store/      # Redis checkpointing + streaming
│   └── guardrail/        # SafeInferenceV3 engine
├── docker-compose.yml
├── Dockerfile.gateway
├── requirements.txt
└── test_e2e.py
```

## Configuration

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Key settings:
- `REDIS_URL` — Redis connection string
- `OLLAMA_BASE_URL` — Ollama API endpoint
- `GUARDRAIL_*` — Guardrail thresholds

## Development

### Add New Agent
```python
from apps.orchestrator import get_orchestrator

orchestrator = await get_orchestrator()
orchestrator.register_agent(AgentDefinition(
    id="my-agent",
    version="1.0.0",
    dag={...},
    compute_profile=ComputeTarget.LOCAL_OLLAMA,
))
```

### Run Lint/Typecheck
```bash
ruff check .
mypy apps/ libs/
```

## Roadmap

See `.opencode/plans/plan.md` for full architectural blueprint.

## License

Internal use only.
