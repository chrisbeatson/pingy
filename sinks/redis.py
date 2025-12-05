"""
Redis sink implementation for time series ping data.

Uses Redis sorted sets to store time series data with automatic expiration.
Key format: ts:latency:{ip}
Score: timestamp in milliseconds
Value: latency_ms

Copyright (c) 2025 Chris Beatson (chris@chrisbeatson.com)
Licensed under the MIT License.
"""

import logging
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
from redis import asyncio as aioredis
from .base import DataSink

logger = logging.getLogger(__name__)


class RedisSink(DataSink):
    """
    Redis sink implementation using sorted sets.

    Stores ping metrics in Redis sorted sets where:
    - Key: ts:latency:{ip}
    - Score: Unix timestamp in milliseconds
    - Member: latency_ms value

    Each key has a TTL for automatic cleanup of old data.
    """

    def __init__(
        self,
        host: str,
        port: int,
        password: Optional[str] = None,
        db: int = 0,
        ttl: int = 86400
    ):
        """
        Initialize Redis sink.

        Args:
            host: Redis host address
            port: Redis port
            password: Optional password for authentication
            db: Database number (0-15)
            ttl: Time-to-live in seconds for data retention (default: 24 hours)
        """
        self.host = host
        self.port = port
        self.password = password
        self.db = db
        self.ttl = ttl
        self.client = None

    async def init(self) -> None:
        """Initialize and test Redis connection."""
        try:
            url = f"redis://{self.host}:{self.port}/{self.db}"
            self.client = await aioredis.from_url(
                url,
                password=self.password,
                decode_responses=True
            )

            # Test connection
            await self.client.ping()
            logger.info("Connected to Redis at %s:%s (db=%s, ttl=%ss)",
                       self.host, self.port, self.db, self.ttl)

        except Exception as e:
            raise ConnectionError(f"Could not connect to Redis: {e}")

    async def write_batch(self, documents: List[Dict[str, Any]]) -> Tuple[int, int]:
        """
        Write a batch of documents to Redis using pipelined commands.

        Args:
            documents: List of ping result documents

        Returns:
            Tuple of (success_count, failed_count)
        """
        if not self.client:
            raise RuntimeError("Redis client not initialized")

        pipeline = self.client.pipeline()

        for doc in documents:
            # Parse ISO timestamp to Unix milliseconds
            try:
                timestamp_str = doc["timestamp"]
                # Handle both formats: with/without 'Z' suffix
                if timestamp_str.endswith('Z'):
                    timestamp_str = timestamp_str[:-1] + '+00:00'

                dt = datetime.fromisoformat(timestamp_str)
                timestamp_ms = int(dt.timestamp() * 1000)

                # Key format: ts:latency:{ip}
                key = f"ts:latency:{doc['ip']}"

                # Add to sorted set (score=timestamp, member=latency)
                # Use timestamp as score for time-based queries
                pipeline.zadd(key, {str(doc['latency_ms']): timestamp_ms})

                # Set expiration
                pipeline.expire(key, self.ttl)

            except Exception as e:
                logger.warning("Failed to process document for %s: %s",
                             doc.get('ip', 'unknown'), e)
                continue

        # Execute all commands in pipeline
        try:
            await pipeline.execute()
            # Redis pipeline: all succeed or all fail
            success = len(documents)
            failed = 0
            return success, failed

        except Exception as e:
            logger.error("Redis pipeline execution failed: %s", e)
            return 0, len(documents)

    async def close(self) -> None:
        """Close Redis connection."""
        if self.client:
            logger.info("Closing Redis connection")
            await self.client.close()
            self.client = None

    def get_batch_size(self) -> int:
        """Return optimal batch size for Redis."""
        return 500  # Redis can handle larger batches efficiently

    def get_flush_interval(self) -> float:
        """Return optimal flush interval for Redis."""
        return 1.0  # Flush more frequently due to larger batch size
