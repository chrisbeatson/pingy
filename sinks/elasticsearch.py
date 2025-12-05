"""
Elasticsearch sink implementation for time series ping data.

Uses the async Elasticsearch client with bulk API for efficient writes.

Copyright (c) 2025 Chris Beatson (chris@chrisbeatson.com)
Licensed under the MIT License.
"""

import logging
from typing import List, Dict, Any, Tuple
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from .base import DataSink

logger = logging.getLogger(__name__)


class ElasticsearchSink(DataSink):
    """
    Elasticsearch sink implementation.

    Stores ping metrics in Elasticsearch using the bulk API.
    Each document contains: ip, timestamp, status, and latency_ms.
    """

    def __init__(self, cloud_id: str, api_key_id: str, api_key: str, index: str):
        """
        Initialize Elasticsearch sink.

        Args:
            cloud_id: Elasticsearch cloud ID
            api_key_id: API key ID for authentication
            api_key: API key secret for authentication
            index: Index name for storing documents
        """
        self.cloud_id = cloud_id
        self.api_key_id = api_key_id
        self.api_key = api_key
        self.index = index
        self.client = None

    async def init(self) -> None:
        """Initialize and test Elasticsearch connection."""
        if not all([self.cloud_id, self.api_key_id, self.api_key]):
            raise ValueError(
                "Missing required Elasticsearch configuration "
                "(cloud_id, api_key_id, api_key)"
            )

        self.client = AsyncElasticsearch(
            cloud_id=self.cloud_id,
            api_key=(self.api_key_id, self.api_key)
        )

        # Test connection
        if not await self.client.ping():
            raise ConnectionError(
                f"Could not connect to Elasticsearch at {self.cloud_id}"
            )

        logger.info("Connected to Elasticsearch cloud: %s", self.cloud_id)

    async def write_batch(self, documents: List[Dict[str, Any]]) -> Tuple[int, int]:
        """
        Write a batch of documents to Elasticsearch using bulk API.

        Args:
            documents: List of ping result documents

        Returns:
            Tuple of (success_count, failed_count)
        """
        if not self.client:
            raise RuntimeError("Elasticsearch client not initialized")

        # Transform generic documents to Elasticsearch bulk format
        es_docs = []
        for doc in documents:
            es_docs.append({
                "_index": self.index,
                "_op_type": "create",
                "_source": {
                    "ip": doc["ip"],
                    "@timestamp": doc["timestamp"],
                    "status": doc["status"],
                    "latency_ms": doc["latency_ms"],
                }
            })

        # Execute bulk write
        success, failed = await async_bulk(
            self.client,
            es_docs,
            stats_only=True
        )

        return success, failed

    async def close(self) -> None:
        """Close Elasticsearch connection."""
        if self.client:
            logger.info("Closing Elasticsearch connection")
            await self.client.close()
            self.client = None

    def get_batch_size(self) -> int:
        """Return optimal batch size for Elasticsearch."""
        return 200

    def get_flush_interval(self) -> float:
        """Return optimal flush interval for Elasticsearch."""
        return 2.0
