# Pingy

A high-performance distributed network monitoring system that performs concurrent ICMP pings and stores latency metrics in your choice of backend storage. Built with Python asyncio for efficient concurrent I/O operations.

## Features

- **Pluggable Storage Backends**: Choose between Elasticsearch, Redis, or add your own
- **Asyncio Architecture**: Efficient concurrent ping operations using cooperative multitasking
- **Dynamic Target Loading**: Automatically reloads target IPs from file at configurable intervals
- **Batched Writes**: Optimized batch writes to minimize backend load
- **Performance Optimizations**: Built-in jitter and shuffling to prevent network congestion
- **Comprehensive Logging**: Structured logging with configurable levels

## Architecture Overview

Pingy uses an asyncio-based architecture with coroutines communicating through queues:

```
targets.txt → Payload Generator → Job Queue → Worker Pool (100 workers) → Output Queue → Sink Writer → Backend
```

### Components

- **Payload Generator**: Reads target file and queues IPs for pinging
- **Worker Pool**: 100+ concurrent workers that ping targets using thread pool executor
- **Sink Writer**: Batches results and writes to configured backend
- **Data Sinks**: Pluggable backends (Elasticsearch, Redis, Prometheus, etc.)

### Supported Backends

| Backend | Use Case | Batch Size | Flush Interval |
|---------|----------|------------|----------------|
| **Elasticsearch** | Long-term storage, complex queries, visualization | 200 | 2s |
| **Redis** | Fast access, short-term cache, real-time queries | 500 | 1s |

## Installation

### Prerequisites

- Python 3.8 or higher
- Root/sudo privileges (required for ICMP raw sockets)
- Backend infrastructure (Elasticsearch Cloud or Redis server)

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/chrisbeatson/pingy.git
   cd pingy
   ```

2. **Create and activate virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your backend credentials and preferences
   ```

5. **Create targets file:**
   ```bash
   cat > targets.txt << EOF
   192.168.1.1
   192.168.1.2
   8.8.8.8
   EOF
   ```

## Configuration

All configuration is managed through environment variables in the `.env` file.

### Core Settings

```bash
# Data Sink Configuration
SINK_TYPE=elasticsearch  # Options: elasticsearch, redis

# Target Configuration
TARGET_FILE=targets.txt  # Path to file with target IPs (one per line)

# Monitoring Configuration
PING_INTERVAL=15         # Seconds between ping cycles
REFRESH_INTERVAL=60      # Seconds between re-reading target file
NUM_WORKERS=100          # Number of concurrent ping workers

# Logging
LOG_LEVEL=INFO          # DEBUG, INFO, WARNING, ERROR
```

### Elasticsearch Backend

```bash
SINK_TYPE=elasticsearch
ES_CLOUD_ID=your-cloud-id-here
ES_API_KEY_ID=your-api-key-id-here
ES_API_KEY=your-api-key-secret-here
ES_INDEX=pingy-metrics
```

**Elasticsearch Setup:**
1. Create an Elastic Cloud deployment at https://cloud.elastic.co
2. Generate an API key with write permissions
3. Add credentials to `.env`

### Redis Backend

```bash
SINK_TYPE=redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=          # Optional
REDIS_DB=0
REDIS_TTL=86400         # Data retention in seconds (24 hours)
```

**Redis Data Structure:**
- Keys: `ts:latency:{ip}`
- Sorted sets with timestamp as score, latency as member
- Automatic expiration via TTL

**Query Example:**
```bash
# Get last hour of data for an IP
redis-cli ZRANGEBYSCORE "ts:latency:192.168.1.1" $(($(date +%s)*1000-3600000)) +inf
```

## Running Pingy

**Important:** ICMP ping requires root privileges for raw socket access.

```bash
# Activate virtual environment
source venv/bin/activate

# Run with sudo (preserves virtual environment)
sudo $(which python3) pingy.py

# Or run directly as root
sudo python3 pingy.py
```

### Running as a System Service

Create a systemd service file at `/etc/systemd/system/pingy.service`:

```ini
[Unit]
Description=Pingy Network Monitor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/pingy
Environment="PATH=/opt/pingy/venv/bin"
ExecStart=/opt/pingy/venv/bin/python3 /opt/pingy/pingy.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable pingy
sudo systemctl start pingy
sudo systemctl status pingy
```

### Running in Docker

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY pingy.py .
COPY sinks/ ./sinks/
COPY .env .

# Run as root (needed for ICMP)
CMD ["python", "pingy.py"]
```

Build and run:
```bash
docker build -t pingy .
docker run -d --name pingy --cap-add=NET_RAW pingy
```

## Target File Management

### Manual File

Simple text file with one IP per line:
```
# Production servers
192.168.1.10
192.168.1.11

# Office network
10.0.0.1
10.0.0.2
```

### Auto-Generated Targets

Pingy automatically reloads `targets.txt` every `REFRESH_INTERVAL` seconds, making it easy to integrate with external systems.

#### From Network Scan

```bash
#!/bin/bash
# Generate targets from nmap scan
nmap -sn 192.168.1.0/24 -oG - | awk '/Up$/{print $2}' > targets.txt
```

#### From Database

```bash
#!/bin/bash
# PostgreSQL example
psql -h db.example.com -U monitoring -d inventory \
  -t -A -c "SELECT ip FROM hosts WHERE active=true AND monitor=true" \
  > targets.txt
```

#### From Cloud Provider

```bash
#!/bin/bash
# AWS EC2 instances
aws ec2 describe-instances \
  --filters "Name=instance-state-name,Values=running" \
            "Name=tag:Monitor,Values=true" \
  --query 'Reservations[*].Instances[*].PrivateIpAddress' \
  --output text | tr '\t' '\n' > targets.txt

# GCP instances
gcloud compute instances list \
  --filter="status=RUNNING AND labels.monitor=true" \
  --format="value(networkInterfaces[0].networkIP)" \
  > targets.txt

# Azure VMs
az vm list -d \
  --query "[?powerState=='VM running' && tags.monitor=='true'].privateIps" \
  -o tsv > targets.txt
```

#### From Kubernetes

```bash
#!/bin/bash
# Get all pod IPs from specific namespace
kubectl get pods -n production -o jsonpath='{.items[*].status.podIP}' \
  | tr ' ' '\n' > targets.txt

# Get all node IPs
kubectl get nodes -o jsonpath='{.items[*].status.addresses[?(@.type=="InternalIP")].address}' \
  | tr ' ' '\n' > targets.txt
```

#### From Configuration Management

```python
#!/usr/bin/env python3
# Generate from Ansible inventory
import json
import subprocess

result = subprocess.run(['ansible-inventory', '--list'],
                       capture_output=True, text=True)
inventory = json.loads(result.stdout)

with open('targets.txt', 'w') as f:
    for host, data in inventory.get('_meta', {}).get('hostvars', {}).items():
        if data.get('monitor', False):
            f.write(f"{data.get('ansible_host', host)}\n")
```

#### Automated Updates with Cron

```bash
# Update targets every 5 minutes
*/5 * * * * /opt/pingy/scripts/update-targets.sh
```

## Infrastructure Guidelines

### Elasticsearch Deployment

**Recommended Configuration:**
- **Deployment size**: Start with 4GB RAM, 2 vCPU
- **Storage**: 50GB with auto-expand
- **Index lifecycle**: Set up ILM policy to roll over daily and delete after 30 days
- **Shards**: 1 primary shard for small deployments (<1M docs/day)
- Index type: Use a datastream

**Index Template:**
```json
{
  "index_patterns": ["pingy-metrics*"],
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1,
      "refresh_interval": "5s"
    },
    "mappings": {
      "properties": {
        "@timestamp": { "type": "date" },
        "ip": { "type": "ip" },
        "status": { "type": "keyword" },
        "latency_ms": { "type": "float" }
      }
    }
  }
}
```

**Scaling Guidelines:**
- Up to 1,000 targets: Single 4GB node
- 1,000-10,000 targets: 8GB node with 2 data nodes
- 10,000+ targets: Multi-node cluster with hot/warm architecture

### Redis Deployment

**Recommended Configuration:**
- **Memory**: Calculate as `(targets × samples_per_day × 32 bytes) × 1.5`
  - Example: 1,000 targets × 5,760 samples/day (15s interval) × 32 bytes × 1.5 = ~276MB
- **Persistence**: RDB snapshots every 5 minutes (not critical if only used as cache)
- **Eviction**: Set `maxmemory-policy allkeys-lru` if memory constrained

**Redis Configuration:**
```bash
maxmemory 2gb
maxmemory-policy allkeys-lru
save 300 10  # Snapshot every 5 minutes if 10+ keys changed
```

**Scaling Guidelines:**
- Up to 5,000 targets: Single Redis instance (2GB)
- 5,000-20,000 targets: Single instance (8GB) or Redis cluster
- 20,000+ targets: Redis cluster with sharding by IP

### Network Considerations

**Bandwidth:**
- ICMP packets: ~84 bytes per ping (IP header + ICMP)
- Per target: ~5KB/day at 15s interval
- 1,000 targets: ~5MB/day (~58 bits/sec)
- 10,000 targets: ~50MB/day (~579 bits/sec)

**Firewall Rules:**
- Outbound: Allow ICMP echo request to all target networks
- No inbound rules needed for ping functionality

### Performance Tuning

**High Target Count (10,000+):**
```bash
NUM_WORKERS=500          # Increase worker pool
PING_INTERVAL=30         # Longer interval
REFRESH_INTERVAL=300     # Less frequent reload
```

**Low Latency Requirements:**
```bash
NUM_WORKERS=200
PING_INTERVAL=5          # More frequent pings
```

**Resource Constrained:**
```bash
NUM_WORKERS=50
PING_INTERVAL=60
LOG_LEVEL=WARNING        # Reduce logging overhead
```

## Adding New Backends

Pingy's pluggable architecture makes it easy to add new storage backends.

### 1. Create Sink Implementation

Create `sinks/yourbackend.py`:

```python
from .base import DataSink
import logging

logger = logging.getLogger(__name__)

class YourBackendSink(DataSink):
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.client = None

    async def init(self):
        # Initialize connection
        self.client = await connect_to_backend(self.host, self.port)
        logger.info("Connected to YourBackend at %s:%s", self.host, self.port)

    async def write_batch(self, documents):
        # Write documents to backend
        # documents is list of dicts with: ip, timestamp, status, latency_ms
        await self.client.write(documents)
        return len(documents), 0  # (success_count, failed_count)

    async def close(self):
        if self.client:
            await self.client.close()

    def get_batch_size(self):
        return 100  # Optimal batch size for your backend

    def get_flush_interval(self):
        return 2.0  # Max seconds before flushing
```

### 2. Register in Factory

Edit `sinks/__init__.py`:

```python
from .yourbackend import YourBackendSink

def create_sink(sink_type: str, config: dict) -> DataSink:
    # ... existing cases ...

    elif sink_type == "yourbackend":
        return YourBackendSink(
            host=config.get("YOURBACKEND_HOST"),
            port=int(config.get("YOURBACKEND_PORT", 1234))
        )
```

### 3. Add Configuration

Edit `pingy.py` to add config keys to `SINK_CONFIG`:

```python
SINK_CONFIG = {
    # ... existing configs ...

    # Your Backend configuration
    "YOURBACKEND_HOST": os.getenv("YOURBACKEND_HOST", "localhost"),
    "YOURBACKEND_PORT": os.getenv("YOURBACKEND_PORT", "1234"),
}
```

### 4. Update Documentation

Add configuration example to `.env.example`:

```bash
# YourBackend Configuration (when SINK_TYPE=yourbackend)
YOURBACKEND_HOST=localhost
YOURBACKEND_PORT=1234
```

## Monitoring Pingy

### Log Analysis

```bash
# Monitor in real-time
tail -f /var/log/syslog | grep pingy

# Check for errors
journalctl -u pingy -p err -f

# View statistics
journalctl -u pingy | grep "flushed"
```

### Health Checks

```python
# Simple health check script
import redis
import datetime

r = redis.Redis(host='localhost', port=6379)

# Check if recent data exists (last 5 minutes)
five_min_ago = (datetime.datetime.now().timestamp() - 300) * 1000
keys = r.keys('ts:latency:*')

healthy = 0
for key in keys[:10]:  # Sample 10 keys
    count = r.zcount(key, five_min_ago, '+inf')
    if count > 0:
        healthy += 1

print(f"Health: {healthy}/10 targets have recent data")
```

## Troubleshooting

### Permission Denied (ICMP)

```
OSError: [Errno 1] Operation not permitted
```

**Solution:** Run with sudo/root privileges:
```bash
sudo python3 pingy.py
```

### Connection Failed

```
Error initializing elasticsearch sink: Could not connect
```

**Solution:** Check credentials and network connectivity:
```bash
# Test Elasticsearch
curl -H "Authorization: ApiKey base64(api_key_id:api_key)" https://your-cloud-id

# Test Redis
redis-cli -h localhost -p 6379 ping
```

### High Memory Usage

**Solution:** Reduce worker count and increase intervals:
```bash
NUM_WORKERS=50
PING_INTERVAL=30
```

### Targets Not Loading

**Solution:** Check file permissions and format:
```bash
# Verify file exists and is readable
ls -l targets.txt
cat targets.txt

# Check logs
grep "Loading targets" /var/log/pingy.log
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Copyright (c) 2025 Chris Beatson (chris@chrisbeatson.com)

## Contributing

Contributions welcome! Please submit pull requests or open issues for bugs and feature requests.

## Support

For questions and support, please open an issue on GitHub.
