"""
Data sink factory and exports.

Provides a factory function to create the appropriate data sink
based on configuration, along with exports of all sink classes.

Copyright (c) 2025 Chris Beatson (chris@chrisbeatson.com)
Licensed under the MIT License.
"""

from .base import DataSink
from .elasticsearch import ElasticsearchSink
from .redis import RedisSink


def create_sink(sink_type: str, config: dict) -> DataSink:
    """
    Factory function to create the appropriate data sink.

    Args:
        sink_type: Type of sink to create ("elasticsearch", "redis", etc.)
        config: Dictionary containing all configuration values

    Returns:
        Initialized DataSink instance (not yet connected)

    Raises:
        ValueError: If sink_type is unknown or required config is missing
    """
    sink_type = sink_type.lower()

    if sink_type == "elasticsearch":
        return ElasticsearchSink(
            cloud_id=config.get("ES_CLOUD_ID"),
            api_key_id=config.get("ES_API_KEY_ID"),
            api_key=config.get("ES_API_KEY"),
            index=config.get("ES_INDEX", "beatson-cpe-metrics")
        )

    elif sink_type == "redis":
        return RedisSink(
            host=config.get("REDIS_HOST", "localhost"),
            port=int(config.get("REDIS_PORT", 6379)),
            password=config.get("REDIS_PASSWORD"),
            db=int(config.get("REDIS_DB", 0)),
            ttl=int(config.get("REDIS_TTL", 86400))
        )

    else:
        raise ValueError(
            f"Unknown sink type: '{sink_type}'. "
            f"Available options: elasticsearch, redis"
        )


__all__ = [
    "DataSink",
    "ElasticsearchSink",
    "RedisSink",
    "create_sink"
]
