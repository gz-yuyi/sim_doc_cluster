# Document Similarity Clustering System

A high-performance system for detecting similar documents using Elasticsearch and Redis, implementing MinHash + LSH for efficient similarity detection and Jaccard similarity for precise matching.

## Features

- **Real-time Processing**: Handles 10,000-15,000 articles per day with real-time similarity detection
- **High Accuracy**: Uses 80% text overlap threshold with Jaccard similarity for precise matching
- **Scalable Architecture**: Elasticsearch for storage and search, Redis for queue management
- **Fast Algorithms**: SimHash for exact duplicate detection, MinHash + LSH for candidate filtering

## Quick Start

### Prerequisites

- Python 3.12+
- Elasticsearch 8.x
- Redis 6.x+
- uv (recommended) or pip

### Installation

1. Clone repository:
```bash
git clone <repository-url>
cd sim-doc-cluster
```

2. Install dependencies:
```bash
uv sync
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your Elasticsearch and Redis settings
```

4. Initialize Elasticsearch indices:
```bash
uv run python main.py init
```

5. Start API server:
```bash
uv run python main.py serve
```

The API will be available at `http://localhost:8000` with interactive docs at `http://localhost:8000/docs`.

## Commands

### Start API Server
```bash
uv run python main.py serve --host 0.0.0.0 --port 8000 --reload
```

### Run Worker
```bash
uv run python main.py worker --count 100
```

### Check External Services
```bash
uv run python main.py check-external-service
```

### Export OpenAPI Spec
```bash
uv run python main.py openapi --output api.json
```

## API Documentation

For detailed API documentation, see [docs/api.md](docs/api.md).

## Algorithm Details

- **SimHash**: 64-bit fingerprint for exact duplicate detection
- **MinHash + LSH**: 128 hash values divided into 20 bands for candidate filtering
- **Jaccard Similarity**: 5-gram character shingles for precise similarity calculation

## Performance

- **Throughput**: 10,000-15,000 articles/day
- **Latency**: <200ms per article (including candidate search)
- **Accuracy**: 80% text overlap threshold