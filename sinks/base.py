"""
Abstract base class for data sinks.

All sink implementations must inherit from DataSink and implement
the required methods for initialization, writing, and cleanup.

Copyright (c) 2025 Chris Beatson (chris@chrisbeatson.com)
Licensed under the MIT License.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple


class DataSink(ABC):
    """Abstract base class for all data sinks."""

    @abstractmethod
    async def init(self) -> None:
        """
        Initialize connection and validate configuration.

        Raises:
            ConnectionError: If unable to connect to the backend
            ValueError: If configuration is invalid
        """
        pass

    @abstractmethod
    async def write_batch(self, documents: List[Dict[str, Any]]) -> Tuple[int, int]:
        """
        Write a batch of documents to the backend.

        Args:
            documents: List of document dictionaries with keys:
                - ip: Target IP address (str)
                - timestamp: ISO 8601 timestamp (str)
                - status: "UP" or "DOWN" (str)
                - latency_ms: Latency in milliseconds (float)

        Returns:
            Tuple of (success_count, failed_count)
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """
        Clean up connections and resources.
        """
        pass

    @abstractmethod
    def get_batch_size(self) -> int:
        """
        Return the optimal batch size for this sink.

        Returns:
            Number of documents to batch before writing
        """
        pass

    @abstractmethod
    def get_flush_interval(self) -> float:
        """
        Return the optimal flush interval in seconds for this sink.

        Returns:
            Maximum seconds to wait before flushing an incomplete batch
        """
        pass
