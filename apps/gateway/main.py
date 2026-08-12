import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from apps.orchestrator import close_orchestrator, get_orchestrator
from libs.shared.schemas import (
    ErrorResponse,
    InferenceRequest,
    StreamingChunk,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MAX_REQUEST_SIZE = 1024 * 1024  # 1MB


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_SIZE:
            return JSONResponse(
                status_code=413,
                content={"error": "Request too large", "code": "PAYLOAD_TOO_LARGE"},
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting API Gateway...")
    yield
    logger.info("Shutting down API Gateway...")
    await close_orchestrator()


app = FastAPI(
    title="aware.ai API Gateway",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_request_id(request: Request) -> uuid.UUID:
    header_id = request.headers.get("X-Request-ID")
    if header_id:
        try:
            return uuid.UUID(header_id)
        except ValueError:
            pass
    return uuid.uuid4()


@app.post("/v1/inference")
@app.post("/v1/inference/")
async def inference(
    request: Request,
    request_id: uuid.UUID = Depends(get_request_id),
):
    try:
        body = await request.json()
        inference_request = InferenceRequest(
            **body,
            request_id=request_id,
        )
    except ValidationError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Request parsing error: {e}")
        raise HTTPException(status_code=400, detail="Invalid request format")

    logger.info(f"Inference request {inference_request.request_id}: agent={inference_request.agent_id}")

    orchestrator = await get_orchestrator()

    if inference_request.stream:
        return StreamingResponse(
            _stream_response(orchestrator, inference_request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Request-ID": str(inference_request.request_id),
            },
        )
    else:
        chunks = []
        async for chunk in _stream_response(orchestrator, inference_request):
            chunks.append(chunk)
        return _format_non_streaming_response(chunks)


async def _stream_response(
    orchestrator,
    request: InferenceRequest,
) -> AsyncGenerator[str, None]:
    request_id = request.request_id
    last_heartbeat = time.time()
    HEARTBEAT_INTERVAL = 15.0

    try:
        async for chunk in orchestrator.execute(request):
            # Send heartbeat if needed
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                yield ": keepalive\n\n"
                last_heartbeat = now

            sse_data = chunk.model_dump_json()
            yield f"data: {sse_data}\n\n"

            if chunk.is_final:
                break
    except Exception as e:
        logger.error(f"Stream error for {request_id}: {e}")
        error_chunk = StreamingChunk(
            request_id=request_id,
            content=f"Internal error: {e!s}",
            finish_reason="error",
            is_final=True,
        )
        yield f"data: {error_chunk.model_dump_json()}\n\n"
    finally:
        yield "data: [DONE]\n\n"


def _format_non_streaming_response(chunks: list) -> JSONResponse:
    content = ""
    for chunk in chunks:
        if chunk.content and not chunk.is_final:
            content += chunk.content

    return JSONResponse(content={
        "choices": [{
            "message": {
                "role": "assistant",
                "content": content,
            },
            "finish_reason": "stop",
            "index": 0,
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "aware.ai-gateway"}


@app.get("/health/ready")
async def ready():
    orchestrator = await get_orchestrator()
    store_healthy = await orchestrator.store.health_check() if orchestrator.store else False
    ollama_healthy = await orchestrator.ollama.health_check() if orchestrator.ollama else False

    return {
        "status": "ready" if store_healthy and ollama_healthy else "degraded",
        "dependencies": {
            "redis": store_healthy,
            "ollama": ollama_healthy,
        },
    }


@app.get("/v1/agents")
async def list_agents():
    orchestrator = await get_orchestrator()
    return {
        "agents": [
            {
                "id": agent.id,
                "version": agent.version,
                "compute_profile": agent.compute_profile.value,
                "privacy_level": agent.privacy_level.value,
            }
            for agent in orchestrator.agents.values()
        ]
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            code="INTERNAL_ERROR",
            request_id=uuid.uuid4(),
        ).model_dump(),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)