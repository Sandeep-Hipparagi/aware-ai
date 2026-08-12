import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
from redis.asyncio import Redis

from libs.shared.schemas import ExecutionContext, ExecutionStatus

logger = logging.getLogger(__name__)


class RedisStore:
    def __init__(self, url: str = "redis://localhost:6379", ttl_seconds: int = 86400):
        self.url = url
        self.ttl = ttl_seconds
        self._client: Redis | None = None
        self._pubsub: redis.client.PubSub | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(
            self.url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
        await self._client.ping()
        logger.info(f"Connected to Redis at {self.url}")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
        if self._pubsub:
            await self._pubsub.close()

    def _context_key(self, request_id: str) -> str:
        return f"execution:{request_id}"

    def _stream_key(self, request_id: str) -> str:
        return f"stream:{request_id}"

    async def save_context(self, context: ExecutionContext) -> None:
        if not self._client:
            raise RuntimeError("Redis not connected")
        key = self._context_key(str(context.request_id))
        data = context.model_dump(mode="json")
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._client.setex(key, self.ttl, json.dumps(data))
        logger.debug(f"Saved context for {context.request_id}")

    async def get_context(self, request_id: str) -> ExecutionContext | None:
        if not self._client:
            raise RuntimeError("Redis not connected")
        key = self._context_key(request_id)
        data = await self._client.get(key)
        if not data:
            return None
        parsed = json.loads(data)
        return ExecutionContext(**parsed)

    async def update_status(self, request_id: str, status: ExecutionStatus, node: str | None = None) -> None:
        context = await self.get_context(request_id)
        if context:
            context.status = status
            context.updated_at = datetime.now(timezone.utc)
            if node:
                context.current_node = node
            await self.save_context(context)

    async def append_checkpoint(self, request_id: str, node_id: str, data: dict[str, Any]) -> None:
        context = await self.get_context(request_id)
        if context:
            context.checkpoint_data[node_id] = {
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            context.updated_at = datetime.now(timezone.utc)
            await self.save_context(context)

    async def get_checkpoint(self, request_id: str, node_id: str) -> dict[str, Any] | None:
        context = await self.get_context(request_id)
        if context and node_id in context.checkpoint_data:
            return context.checkpoint_data[node_id]["data"]
        return None

    async def publish_stream(self, request_id: str, chunk: dict[str, Any]) -> None:
        if not self._client:
            raise RuntimeError("Redis not connected")
        stream_key = self._stream_key(request_id)
        await self._client.xadd(stream_key, {"data": json.dumps(chunk)})
        await self._client.expire(stream_key, 300)

    async def subscribe_stream(self, request_id: str, last_id: str = "0"):
        if not self._client:
            raise RuntimeError("Redis not connected")
        stream_key = self._stream_key(request_id)
        while True:
            try:
                messages = await self._client.xread({stream_key: last_id}, block=5000, count=10)
                for stream, entries in messages:
                    for msg_id, data in entries:
                        last_id = msg_id
                        yield json.loads(data["data"])
            except Exception as e:
                logger.error(f"Stream subscription error: {e}")
                break

    async def delete_context(self, request_id: str) -> None:
        if not self._client:
            raise RuntimeError("Redis not connected")
        await self._client.delete(self._context_key(request_id))
        await self._client.delete(self._stream_key(request_id))

    async def health_check(self) -> bool:
        try:
            if self._client:
                await self._client.ping()
                return True
        except Exception:
            pass
        return False


_store: RedisStore | None = None


async def get_store() -> RedisStore:
    global _store
    if _store is None:
        _store = RedisStore()
        await _store.connect()
    return _store


async def close_store() -> None:
    global _store
    if _store:
        await _store.disconnect()
        _store = None