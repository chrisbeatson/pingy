#!/usr/bin/env python3
"""
Pingy - High-performance distributed network monitoring system

Copyright (c) 2025 Chris Beatson (chris@chrisbeatson.com)
Licensed under the MIT License. See LICENSE file for details.
"""

import asyncio
import random
import logging
import os
import ipaddress
from ping3 import ping
from datetime import datetime, timezone
from dotenv import load_dotenv
from sinks import create_sink

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
TARGET_FILE = os.getenv("TARGET_FILE", "targets.txt")

# Data Sink Configuration
SINK_TYPE = os.getenv("SINK_TYPE", "elasticsearch")

# Sink-specific configuration (loaded into config dict)
SINK_CONFIG = {
    # Elasticsearch configuration
    "ES_CLOUD_ID": os.getenv("ES_CLOUD_ID"),
    "ES_API_KEY_ID": os.getenv("ES_API_KEY_ID"),
    "ES_API_KEY": os.getenv("ES_API_KEY"),
    "ES_INDEX": os.getenv("ES_INDEX", "beatson-cpe-metrics"),

    # Redis configuration
    "REDIS_HOST": os.getenv("REDIS_HOST", "localhost"),
    "REDIS_PORT": os.getenv("REDIS_PORT", "6379"),
    "REDIS_PASSWORD": os.getenv("REDIS_PASSWORD"),
    "REDIS_DB": os.getenv("REDIS_DB", "0"),
    "REDIS_TTL": os.getenv("REDIS_TTL", "86400"),
}

# Monitoring configuration
PING_INTERVAL = int(os.getenv("PING_INTERVAL", "15"))
REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "60"))
NUM_WORKERS = int(os.getenv("NUM_WORKERS", "100"))

# Global list of targets (no lock needed with asyncio)
TARGETS = []

# Queues
job_queue = asyncio.Queue()
output_queue = asyncio.Queue()

# Initialize Data Sink
data_sink = None


async def init_data_sink():
    """Initialize the configured data sink."""
    global data_sink

    try:
        logger.info("Initializing %s sink...", SINK_TYPE)
        data_sink = create_sink(SINK_TYPE, SINK_CONFIG)
        await data_sink.init()
        logger.info("Data sink initialized successfully")
    except Exception as e:
        logger.error("Error initializing %s sink: %s", SINK_TYPE, e)
        exit(1)


def validate_ip_address(ip):
    """Validate that a string is a valid IP address."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def validate_targets(targets):
    """
    Validate that targets are valid IP addresses.
    Returns tuple of (valid_targets, invalid_count)
    """
    if not isinstance(targets, list):
        logger.error("Targets must be a list, got %s", type(targets).__name__)
        return [], 0

    valid = []
    invalid_count = 0

    for target in targets:
        if isinstance(target, str) and validate_ip_address(target):
            valid.append(target)
        else:
            logger.warning("Invalid target (not a valid IP): %s", target)
            invalid_count += 1

    return valid, invalid_count


async def load_targets_from_file():
    """
    Load targets from a local file (one IP per line).
    Expected format: One IP address per line in targets.txt
    """
    global TARGETS
    try:
        # Check if file exists
        if not os.path.exists(TARGET_FILE):
            logger.warning("Target file not found: %s", TARGET_FILE)
            return

        logger.info("Loading targets from %s", TARGET_FILE)

        # Read file
        with open(TARGET_FILE, 'r') as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        # Validate and update
        valid_targets, invalid_count = validate_targets(lines)

        if valid_targets:
            TARGETS = valid_targets
            logger.info("Loaded %d targets from %s (invalid: %d)",
                       len(valid_targets), TARGET_FILE, invalid_count)
        else:
            logger.error("No valid targets in %s", TARGET_FILE)

    except Exception as e:
        logger.error("Failed to load targets from %s: %s", TARGET_FILE, e)


async def pinger_worker(worker_id):
    """
    Worker coroutine that pulls an IP, pings it, and pushes to Output Queue.
    """
    loop = asyncio.get_event_loop()

    while True:
        try:
            target = await job_queue.get()
            if target is None:
                break

            # Add Jitter: Random sleep between 10ms and 100ms
            await asyncio.sleep(random.uniform(0.01, 0.1))

            try:
                # Run blocking ping in executor to avoid blocking event loop
                rtt_seconds = await loop.run_in_executor(
                    None, ping, target, 2, "s"
                )
            except OSError:
                rtt_seconds = None

            timestamp = datetime.now(timezone.utc).isoformat()

            status = "DOWN"
            latency_ms = 0.0

            if rtt_seconds is not None:
                status = "UP"
                latency_ms = round(rtt_seconds * 1000, 2)

            # Construct generic document (sink-agnostic format)
            doc = {
                "ip": target,
                "timestamp": timestamp,
                "status": status,
                "latency_ms": latency_ms,
            }

            await output_queue.put(doc)
            job_queue.task_done()

        except Exception as e:
            logger.error("Error in worker %d: %s", worker_id, e)
            job_queue.task_done()


async def sink_writer_worker():
    """
    Generic writer coroutine that batches and writes to the configured data sink.
    """
    logger.info("Starting %s Writer", SINK_TYPE.title())

    # Get optimal batch settings from the sink
    batch_size = data_sink.get_batch_size()
    flush_interval = data_sink.get_flush_interval()

    logger.info("Writer settings: batch_size=%d, flush_interval=%.1fs",
               batch_size, flush_interval)

    buffer = []
    last_flush_time = asyncio.get_event_loop().time()

    while True:
        try:
            # Try to get an item with short timeout
            doc = await asyncio.wait_for(output_queue.get(), timeout=0.1)
            buffer.append(doc)
        except asyncio.TimeoutError:
            pass

        current_time = asyncio.get_event_loop().time()
        time_since_flush = current_time - last_flush_time

        # Flush if buffer is full OR time limit reached
        if len(buffer) >= batch_size or (
            len(buffer) > 0 and time_since_flush >= flush_interval
        ):
            try:
                success, failed = await data_sink.write_batch(buffer)
                logger.info("Writer flushed %d docs (failed: %d)", success, failed)
            except Exception as e:
                logger.error("Batch write failed: %s", e)

            buffer = []
            last_flush_time = current_time


async def payload_generator():
    """
    Master loop:
    1. Checks if list needs refreshing.
    2. Queues all targets.
    3. Sleeps remainder of interval.
    """
    last_refresh_time = 0

    while True:
        cycle_start_time = asyncio.get_event_loop().time()

        # 1. Check if we need to refresh the IP list
        current_time = asyncio.get_event_loop().time()
        if current_time - last_refresh_time > REFRESH_INTERVAL:
            await load_targets_from_file()
            last_refresh_time = current_time

        # 2. Queue up the current list of targets
        current_batch = list(TARGETS)

        # Shuffle to prevent hammering specific subnets
        random.shuffle(current_batch)

        if not current_batch:
            logger.warning("No targets to ping. Waiting...")
        else:
            logger.info("Queuing %d targets for ping cycle", len(current_batch))
            for target in current_batch:
                await job_queue.put(target)

        # 3. Wait for the next cycle
        elapsed = asyncio.get_event_loop().time() - cycle_start_time
        sleep_time = max(0, PING_INTERVAL - elapsed)

        if sleep_time == 0:
            logger.warning("Cycle took longer than interval! Consider increasing workers.")

        await asyncio.sleep(sleep_time)


async def start_monitor():
    """Main async function that coordinates all tasks."""
    logger.info("Starting Pingy Monitor (Async). Sink: %s, Workers: %d, Interval: %ds",
               SINK_TYPE, NUM_WORKERS, PING_INTERVAL)

    # Initialize data sink
    await init_data_sink()

    # Initial load of targets before starting
    await load_targets_from_file()

    # Create all tasks
    tasks = []

    # 1. Start Pinger Workers
    for i in range(NUM_WORKERS):
        task = asyncio.create_task(pinger_worker(i))
        tasks.append(task)

    # 2. Start Sink Writer
    writer_task = asyncio.create_task(sink_writer_worker())
    tasks.append(writer_task)

    # 3. Start Generator (Main Loop)
    generator_task = asyncio.create_task(payload_generator())
    tasks.append(generator_task)

    try:
        # Wait for all tasks (they run forever)
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Stopping monitor...")
        # Send poison pills to workers
        for _ in range(NUM_WORKERS):
            await job_queue.put(None)
        # Wait for workers to finish gracefully
        await asyncio.sleep(1)
    finally:
        if data_sink:
            await data_sink.close()


def main():
    """Entry point that handles asyncio setup and shutdown."""
    try:
        asyncio.run(start_monitor())
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")


if __name__ == "__main__":
    # Requirement: run with sudo
    main()
