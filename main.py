import click
import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from src.api import create_app
from src.config import settings
from src.es_client import es_client
from src.redis_client import redis_client


@click.group()
def cli():
    """Document Similarity Clustering System CLI."""
    pass


@cli.command()
@click.option("--host", default=None, help="Host to bind to")
@click.option("--port", default=None, type=int, help="Port to bind to")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
@click.option("--debug", is_flag=True, help="Enable debug mode")
def serve(host, port, reload, debug):
    """Start the API server."""
    # Override settings with command line options
    if host:
        settings.host = host
    if port:
        settings.port = port
    if debug:
        settings.debug = debug
    
    # Start server; when reload/workers are requested uvicorn needs an import string
    uvicorn_kwargs = dict(
        host=settings.host,
        port=settings.port,
        reload=reload,
        log_level="debug" if settings.debug else "info",
    )

    if reload:
        uvicorn.run("src.api:create_app", factory=True, **uvicorn_kwargs)
    else:
        app = create_app()
        uvicorn.run(app, **uvicorn_kwargs)


@cli.command()
def init():
    """Initialize Elasticsearch indices."""
    click.echo("Initializing Elasticsearch indices...")
    
    try:
        es_client.create_indices()
        click.echo("✓ Elasticsearch indices created successfully")
    except Exception as e:
        click.echo(f"✗ Failed to create Elasticsearch indices: {e}")
        raise


@cli.command()
def health():
    """Check system health."""
    click.echo("Checking system health...")
    
    # Check Elasticsearch
    try:
        if es_client.ping():
            click.echo("✓ Elasticsearch: OK")
        else:
            click.echo("✗ Elasticsearch: FAILED")
    except Exception as e:
        click.echo(f"✗ Elasticsearch: ERROR - {e}")
    
    # Check Redis
    try:
        if redis_client.ping():
            click.echo("✓ Redis: OK")
            
            # Get queue stats
            stats = redis_client.get_queue_stats()
            click.echo(f"  Queue length: {stats['queue_length']}")
            click.echo(f"  Pending jobs: {stats['pending_jobs']}")
        else:
            click.echo("✗ Redis: FAILED")
    except Exception as e:
        click.echo(f"✗ Redis: ERROR - {e}")


@cli.command()
@click.option("--count", default=None, type=int, help="Number of jobs to process")
@click.option("--timeout", default=10, type=int, help="Queue timeout in seconds")
def worker(count, timeout):
    """Run similarity calculation worker."""
    from src.worker import run_worker
    
    click.echo(f"Starting similarity worker...")
    if count:
        click.echo(f"Will process up to {count} jobs")
    
    try:
        run_worker(max_jobs=count, timeout=timeout)
    except KeyboardInterrupt:
        click.echo("Worker stopped by user")
    except Exception as e:
        click.echo(f"Worker error: {e}")
        raise


@cli.command()
def config():
    """Show current configuration."""
    click.echo("Current Configuration:")
    click.echo(f"  App Name: {settings.app_name}")
    click.echo(f"  Version: {settings.app_version}")
    click.echo(f"  Debug: {settings.debug}")
    click.echo(f"  Host: {settings.host}")
    click.echo(f"  Port: {settings.port}")
    click.echo(f"  ES Host: {settings.es_host}:{settings.es_port}")
    click.echo(f"  ES Articles Index: {settings.es_articles_index_full}")
    click.echo(f"  ES Clusters Index: {settings.es_clusters_index_full}")
    click.echo(f"  Redis Host: {settings.redis_host}:{settings.redis_port}")
    click.echo(f"  Redis Queue: {settings.redis_queue_name}")
    click.echo(f"  Similarity Threshold: {settings.similarity_threshold}")
    click.echo(f"  SimHash Bit Size: {settings.simhash_bit_size}")
    click.echo(f"  MinHash Permutations: {settings.minhash_permutations}")
    click.echo(f"  Shingle Size: {settings.shingle_size}")


@cli.command()
@click.option("--output", "-o", default="openapi.json", help="Output file path")
def openapi(output):
    """Export OpenAPI specification."""
    import json
    from pathlib import Path
    
    # Create FastAPI app
    app = create_app()
    
    # Get OpenAPI schema
    openapi_schema = app.openapi()
    
    # Write to file
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
    
    click.echo(f"✓ OpenAPI specification exported to {output_path}")


@cli.command("integration-test")
@click.option("--base-url", default="http://localhost:8000", show_default=True, help="Service base URL")
@click.option("--timeout", default=10, show_default=True, type=int, help="HTTP request timeout in seconds")
def integration_test(base_url, timeout):
    """Run integration tests against the API service."""
    import uuid
    from datetime import datetime, timezone

    import httpx

    click.echo(f"Running integration tests against {base_url}")
    click.echo("-" * 60)

    results = []

    def record(step: str, success: bool, detail: str = ""):
        status_icon = "✅" if success else "❌"
        message = f"{status_icon} {step}"
        if detail:
            message += f" - {detail}"
        click.echo(message)
        results.append(success)
    
    def format_error(response: httpx.Response | None, error: Exception) -> str:
        """Return detailed error information for debugging."""
        if response is None:
            return str(error)
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = response.text
        return f"{error} | status={response.status_code} body={body}"

    article_id = f"it_{uuid.uuid4().hex[:12]}"
    publish_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    test_title = f"Integration Test {article_id}"

    try:
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            # Health check
            try:
                resp = client.get("/api/v1/system/health")
                resp.raise_for_status()
                data = resp.json()
                record("Health endpoint", True, f"status={data.get('status')}")
            except Exception as exc:  # noqa: BLE001
                detail = format_error(locals().get("resp"), exc)
                record("Health endpoint", False, detail)

            # Submit article
            payload = {
                "article_id": article_id,
                "title": test_title,
                "content": "Integration test content",
                "publish_time": publish_time,
                "source": "integration_test",
                "state": 1,
                "top": 0,
                "tags": [{"id": 9999, "name": "integration"}],
                "topic": [{"id": "topic_integration", "name": "integration"}],
            }
            try:
                resp = client.post("/api/v1/articles/", json=payload)
                resp.raise_for_status()
                record("Submit article", True)
            except Exception as exc:  # noqa: BLE001
                detail = format_error(locals().get("resp"), exc)
                record("Submit article", False, detail)

            # Fetch article
            try:
                resp = client.get(f"/api/v1/articles/{article_id}")
                resp.raise_for_status()
                data = resp.json()
                returned_id = data.get("article", {}).get("article_id")
                record("Fetch article", returned_id == article_id, f"id={returned_id}")
            except Exception as exc:  # noqa: BLE001
                detail = format_error(locals().get("resp"), exc)
                record("Fetch article", False, detail)

            # Similar articles (expected 404 while pending or 200 if ready)
            try:
                resp = client.get(f"/api/v1/articles/{article_id}/similar")
                if resp.status_code == 404:
                    error_code = resp.json().get("error", {}).get("code")
                    expected = error_code == "CLUSTER_PENDING"
                    record("Similar articles", expected, f"status=404 code={error_code}")
                else:
                    resp.raise_for_status()
                    record("Similar articles", True, "status=200")
            except Exception as exc:  # noqa: BLE001
                detail = format_error(locals().get("resp"), exc)
                record("Similar articles", False, detail)

            # Search article by title keyword
            try:
                resp = client.get("/api/v1/clusters", params={"title": test_title})
                resp.raise_for_status()
                data = resp.json()
                ids = data.get("article_ids", [])
                record("Article search", article_id in ids, f"found={article_id in ids}")
            except Exception as exc:  # noqa: BLE001
                detail = format_error(locals().get("resp"), exc)
                record("Article search", False, detail)

    except Exception as exc:  # noqa: BLE001
        record("HTTP client setup", False, str(exc))

    click.echo("-" * 60)
    if all(results) and results:
        click.echo("✅ Integration tests passed")
        raise SystemExit(0)
    click.echo("❌ Integration tests failed")
    raise SystemExit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
