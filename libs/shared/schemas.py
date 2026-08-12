from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class PrivacyLevel(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    RESTRICTED = "RESTRICTED"
    SOVEREIGN = "SOVEREIGN"


class ComputeTarget(str, Enum):
    LOCAL_OLLAMA = "LOCAL_OLLAMA"
    SARVAM_SOVEREIGN = "SARVAM_SOVEREIGN"
    NVIDIA_H100 = "NVIDIA_H100"
    NVIDIA_H200 = "NVIDIA_H200"


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    ROUTING = "ROUTING"
    PRE_GUARDRAIL = "PRE_GUARDRAIL"
    EXECUTING = "EXECUTING"
    POST_GUARDRAIL = "POST_GUARDRAIL"
    STREAMING = "STREAMING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GuardrailDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    MODIFY = "MODIFY"


class InferenceRequest(BaseModel):
    prompt: str = Field(..., max_length=100000)
    agent_id: str = Field(..., pattern=r'^[a-z0-9-]+$')
    stream: bool = True
    constraints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InferenceConstraints(BaseModel):
    max_latency_ms: int | None = Field(default=None, ge=100, le=120000)
    privacy_level: PrivacyLevel = PrivacyLevel.INTERNAL
    cost_budget_usd: float | None = Field(default=None, ge=0)
    required_models: list[str] | None = None


class AgentDefinition(BaseModel):
    id: str
    version: str
    dag: dict[str, Any]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    compute_profile: ComputeTarget = ComputeTarget.LOCAL_OLLAMA
    privacy_level: PrivacyLevel = PrivacyLevel.INTERNAL


class ExecutionContext(BaseModel):
    request_id: UUID
    agent_id: str
    agent_version: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    current_node: str | None = None
    checkpoint_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    constraints: InferenceConstraints = Field(default_factory=InferenceConstraints)


class GuardrailResult(BaseModel):
    decision: GuardrailDecision
    reason: str
    modified_prompt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0


class ModelResponse(BaseModel):
    content: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    finish_reason: str = "stop"
    latency_ms: float = 0.0


class StreamingChunk(BaseModel):
    request_id: UUID
    content: str
    finish_reason: str | None = None
    is_final: bool = False


class ErrorResponse(BaseModel):
    error: str
    code: str
    request_id: UUID
    details: dict[str, Any] | None = None