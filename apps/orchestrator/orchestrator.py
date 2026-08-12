import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from libs.guardrail import SafeInferenceV3, get_guardrail
from libs.ollama import get_ollama_client
from libs.redis_store import RedisStore, get_store
from libs.shared.schemas import (
    AgentDefinition,
    ComputeTarget,
    ExecutionContext,
    ExecutionStatus,
    GuardrailDecision,
    InferenceConstraints,
    InferenceRequest,
    PrivacyLevel,
    StreamingChunk,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentNode:
    id: str
    type: str
    config: dict[str, Any] = field(default_factory=dict)
    fallback: str | None = None


@dataclass
class ExecutionGraph:
    nodes: dict[str, AgentNode] = field(default_factory=dict)
    edges: list[tuple] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    exit_points: list[str] = field(default_factory=list)


DEFAULT_AGENTS = {
    "default": AgentDefinition(
        id="default",
        version="1.0.0",
        dag={
            "nodes": {
                "llm": {"id": "llm", "type": "LLM", "config": {"model": "llama3.1:8b"}}
            },
            "edges": [],
            "entry_points": ["llm"],
            "exit_points": ["llm"],
        },
        tools=[],
        policies=["safe_inference_v3"],
        compute_profile=ComputeTarget.LOCAL_OLLAMA,
        privacy_level=PrivacyLevel.INTERNAL,
    ),
    "coding": AgentDefinition(
        id="coding",
        version="1.0.0",
        dag={
            "nodes": {
                "llm": {"id": "llm", "type": "LLM", "config": {"model": "codellama:13b"}}
            },
            "edges": [],
            "entry_points": ["llm"],
            "exit_points": ["llm"],
        },
        tools=[],
        policies=["safe_inference_v3"],
        compute_profile=ComputeTarget.LOCAL_OLLAMA,
        privacy_level=PrivacyLevel.INTERNAL,
    ),
    "reasoning": AgentDefinition(
        id="reasoning",
        version="1.0.0",
        dag={
            "nodes": {
                "llm": {"id": "llm", "type": "LLM", "config": {"model": "llama3.1:8b"}}
            },
            "edges": [],
            "entry_points": ["llm"],
            "exit_points": ["llm"],
        },
        tools=[],
        policies=["safe_inference_v3"],
        compute_profile=ComputeTarget.LOCAL_OLLAMA,
        privacy_level=PrivacyLevel.INTERNAL,
    ),
}


class Orchestrator:
    def __init__(
        self,
        store: RedisStore | None = None,
        ollama: Any | None = None,
        guardrail: SafeInferenceV3 | None = None,
    ):
        self.store = store
        self.ollama = ollama
        self.guardrail = guardrail
        self.agents = DEFAULT_AGENTS.copy()
        self._running = False

    async def initialize(self) -> None:
        if self.store is None:
            self.store = await get_store()
        if self.ollama is None:
            self.ollama = await get_ollama_client()
        if self.guardrail is None:
            self.guardrail = get_guardrail()
        self._running = True
        logger.info("Orchestrator initialized")

    async def shutdown(self) -> None:
        self._running = False
        logger.info("Orchestrator shutdown")

    def register_agent(self, agent: AgentDefinition) -> None:
        self.agents[agent.id] = agent
        logger.info(f"Registered agent: {agent.id} v{agent.version}")

    def get_agent(self, agent_id: str) -> AgentDefinition | None:
        return self.agents.get(agent_id)

    def _build_graph(self, agent: AgentDefinition) -> ExecutionGraph:
        graph = ExecutionGraph()
        dag = agent.dag
        for node_id, node_data in dag.get("nodes", {}).items():
            graph.nodes[node_id] = AgentNode(
                id=node_id,
                type=node_data.get("type", "LLM"),
                config=node_data.get("config", {}),
                fallback=node_data.get("fallback"),
            )
        graph.edges = dag.get("edges", [])
        graph.entry_points = dag.get("entry_points", [])
        graph.exit_points = dag.get("exit_points", [])
        return graph

    def _topological_sort(self, graph: ExecutionGraph) -> list[str]:
        in_degree = {node_id: 0 for node_id in graph.nodes}
        for src, dst in graph.edges:
            in_degree[dst] = in_degree.get(dst, 0) + 1

        queue = [node_id for node_id, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            node_id = queue.pop(0)
            result.append(node_id)
            for src, dst in graph.edges:
                if src == node_id:
                    in_degree[dst] -= 1
                    if in_degree[dst] == 0:
                        queue.append(dst)

        if len(result) != len(graph.nodes):
            raise ValueError("Cycle detected in execution graph")
        return result

    async def execute(
        self,
        request: InferenceRequest,
    ) -> AsyncGenerator[StreamingChunk, None]:
        request_id = request.request_id
        agent = self.get_agent(request.agent_id)

        if not agent:
            yield StreamingChunk(
                request_id=request_id,
                content=f"Agent not found: {request.agent_id}",
                finish_reason="error",
                is_final=True,
            )
            return

        constraints = InferenceConstraints(**(request.constraints or {}))
        context = ExecutionContext(
            request_id=request_id,
            agent_id=agent.id,
            agent_version=agent.version,
            constraints=constraints,
        )

        await self.store.save_context(context)

        # Execution timeout from constraints or default 120s
        exec_timeout = constraints.max_latency_ms / 1000 if constraints.max_latency_ms else 120.0

        try:
            await self.store.update_status(str(request_id), ExecutionStatus.PRE_GUARDRAIL)

            guardrail_result = await self.guardrail.pre_flight(request.prompt)
            if guardrail_result.decision == GuardrailDecision.DENY:
                yield StreamingChunk(
                    request_id=request_id,
                    content=f"Request denied: {guardrail_result.reason}",
                    finish_reason="guardrail_denied",
                    is_final=True,
                )
                await self.store.update_status(str(request_id), ExecutionStatus.FAILED)
                return

            prompt = guardrail_result.modified_prompt or request.prompt
            guardrail_context = guardrail_result.metadata or {}

            graph = self._build_graph(agent)
            execution_order = self._topological_sort(graph)

            await self.store.update_status(str(request_id), ExecutionStatus.EXECUTING)

            accumulated_response = ""
            for node_id in execution_order:
                await self.store.update_status(str(request_id), ExecutionStatus.EXECUTING, node_id)
                node = graph.nodes[node_id]

                if node.type == "LLM":
                    model_name = node.config.get("model", "llama3.1:8b")

                    # Use shared client, pass model via options
                    ollama_client = await get_ollama_client()

                    try:
                        async for chunk in asyncio.wait_for(
                            ollama_client.generate_stream(prompt, options={"model": model_name}),
                            timeout=exec_timeout,
                        ):
                            if chunk.get("content"):
                                accumulated_response += chunk["content"]
                                yield StreamingChunk(
                                    request_id=request_id,
                                    content=chunk["content"],
                                    finish_reason=None,
                                    is_final=False,
                                )

                                await self.store.publish_stream(str(request_id), {
                                    "content": chunk["content"],
                                    "node": node_id,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                })

                        await self.store.append_checkpoint(str(request_id), node_id, {
                            "response": accumulated_response,
                            "model": model_name,
                        })

                    except asyncio.TimeoutError:
                        yield StreamingChunk(
                            request_id=request_id,
                            content=f"Model execution timeout ({exec_timeout}s)",
                            finish_reason="timeout",
                            is_final=True,
                        )
                        await self.store.update_status(str(request_id), ExecutionStatus.FAILED)
                        return

                elif node.type == "TOOL":
                    pass

            await self.store.update_status(str(request_id), ExecutionStatus.POST_GUARDRAIL)

            post_guardrail = await self.guardrail.post_generation(accumulated_response, prompt, guardrail_context)
            if post_guardrail.decision == GuardrailDecision.DENY:
                yield StreamingChunk(
                    request_id=request_id,
                    content=f"Response blocked: {post_guardrail.reason}",
                    finish_reason="guardrail_denied",
                    is_final=True,
                )
                await self.store.update_status(str(request_id), ExecutionStatus.FAILED)
                return

            await self.store.update_status(str(request_id), ExecutionStatus.STREAMING)
            await self.store.update_status(str(request_id), ExecutionStatus.COMPLETED)

            yield StreamingChunk(
                request_id=request_id,
                content="",
                finish_reason="stop",
                is_final=True,
            )

        except Exception as e:
            logger.error(f"Execution error for {request_id}: {e}")
            await self.store.update_status(str(request_id), ExecutionStatus.FAILED)
            yield StreamingChunk(
                request_id=request_id,
                content=f"Execution error: {e!s}",
                finish_reason="error",
                is_final=True,
            )


_orchestrator: Orchestrator | None = None


async def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
        await _orchestrator.initialize()
    return _orchestrator


async def close_orchestrator() -> None:
    global _orchestrator
    if _orchestrator:
        await _orchestrator.shutdown()
        _orchestrator = None