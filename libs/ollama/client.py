import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "llama3.1:8b"
    timeout_seconds: float = 120.0
    keep_alive: str = "5m"
    num_ctx: int = 4096
    num_predict: int = 2048
    temperature: float = 0.7
    top_p: float = 0.9


class OllamaMessage(BaseModel):
    role: str
    content: str


class OllamaGenerateRequest(BaseModel):
    model: str
    prompt: str
    stream: bool = True
    options: dict[str, Any] = {}
    keep_alive: str = "5m"


class OllamaChatRequest(BaseModel):
    model: str
    messages: list[OllamaMessage]
    stream: bool = True
    options: dict[str, Any] = {}
    keep_alive: str = "5m"


class OllamaResponse(BaseModel):
    model: str
    created_at: str
    response: str = ""
    message: OllamaMessage | None = None
    done: bool = False
    context: list[int] | None = None
    total_duration: int = 0
    load_duration: int = 0
    prompt_eval_count: int = 0
    prompt_eval_duration: int = 0
    eval_count: int = 0
    eval_duration: int = 0


class OllamaClient:
    def __init__(self, config: OllamaConfig | None = None):
        self.config = config or OllamaConfig()
        self._client: httpx.AsyncClient | None = None
        self._model_loaded = False

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(self.config.timeout_seconds, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        await self._ensure_model()
        logger.info(f"Ollama client connected to {self.config.base_url}")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_model(self) -> None:
        try:
            response = await self._client.post(
                "/api/show",
                json={"name": self.config.model},
            )
            if response.status_code == 404:
                logger.info(f"Model {self.config.model} not found, pulling...")
                await self._pull_model()
            self._model_loaded = True
        except Exception as e:
            logger.warning(f"Model check failed: {e}")

    async def _pull_model(self) -> None:
        async with self._client.stream(
            "POST",
            "/api/pull",
            json={"name": self.config.model, "stream": True},
            timeout=httpx.Timeout(300.0),
        ) as response:
            async for line in response.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if "status" in data:
                            logger.debug(f"Pull status: {data['status']}")
                    except json.JSONDecodeError:
                        pass

    async def health_check(self) -> bool:
        try:
            if not self._client:
                return False
            response = await self._client.get("/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if not self._client:
            raise RuntimeError("Client not connected")

        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        # Allow model override via options
        model = self.config.model
        if options and "model" in options:
            model = options.pop("model")

        request = OllamaGenerateRequest(
            model=model,
            prompt=full_prompt,
            stream=True,
            options={
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.num_predict,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                **(options or {}),
            },
            keep_alive=self.config.keep_alive,
        )

        start_time = time.time()
        first_token_time = None

        try:
            async with self._client.stream(
                "POST",
                "/api/generate",
                json=request.model_dump(),
                timeout=httpx.Timeout(self.config.timeout_seconds),
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise RuntimeError(f"Ollama error {response.status_code}: {error_text.decode()}")

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        if first_token_time is None and chunk.get("response"):
                            first_token_time = time.time()

                        yield {
                            "content": chunk.get("response", ""),
                            "done": chunk.get("done", False),
                            "model": model,
                            "latency_ms": (time.time() - start_time) * 1000,
                            "ttft_ms": (first_token_time - start_time) * 1000 if first_token_time else None,
                            "eval_count": chunk.get("eval_count", 0),
                        }

                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

        except httpx.TimeoutException:
            raise RuntimeError(f"Ollama request timeout after {self.config.timeout_seconds}s")
        except Exception as e:
            logger.error(f"Ollama generation error: {e}")
            raise

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if not self._client:
            raise RuntimeError("Client not connected")

        ollama_messages = [OllamaMessage(**m) for m in messages]

        request = OllamaChatRequest(
            model=self.config.model,
            messages=ollama_messages,
            stream=True,
            options={
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.num_predict,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                **(options or {}),
            },
            keep_alive=self.config.keep_alive,
        )

        start_time = time.time()
        first_token_time = None

        try:
            async with self._client.stream(
                "POST",
                "/api/chat",
                json=request.model_dump(),
                timeout=httpx.Timeout(self.config.timeout_seconds),
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise RuntimeError(f"Ollama error {response.status_code}: {error_text.decode()}")

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        message = chunk.get("message", {})
                        content = message.get("content", "")

                        if first_token_time is None and content:
                            first_token_time = time.time()

                        yield {
                            "content": content,
                            "done": chunk.get("done", False),
                            "model": self.config.model,
                            "latency_ms": (time.time() - start_time) * 1000,
                            "ttft_ms": (first_token_time - start_time) * 1000 if first_token_time else None,
                            "eval_count": chunk.get("eval_count", 0),
                        }

                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

        except httpx.TimeoutException:
            raise RuntimeError(f"Ollama request timeout after {self.config.timeout_seconds}s")
        except Exception as e:
            logger.error(f"Ollama chat error: {e}")
            raise


_default_client: OllamaClient | None = None


async def get_ollama_client(config: OllamaConfig | None = None) -> OllamaClient:
    global _default_client
    if _default_client is None:
        _default_client = OllamaClient(config)
        await _default_client.connect()
    return _default_client


async def close_ollama_client() -> None:
    global _default_client
    if _default_client:
        await _default_client.disconnect()
        _default_client = None