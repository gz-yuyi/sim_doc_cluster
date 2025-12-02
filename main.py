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


@cli.command("clear-all")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def clear_all(force):
    """Clear all Redis tasks and Elasticsearch documents."""
    if not force:
        proceed = click.confirm(
            "This will delete all Redis jobs and all Elasticsearch documents. Continue?",
            default=False,
        )
        if not proceed:
            click.echo("Aborted.")
            return
    
    click.echo("Clearing Redis tasks...")
    try:
        redis_stats = redis_client.clear_all_tasks()
        click.echo(
            f"  Queue deleted: {redis_stats['queue_deleted']}, "
            f"job keys removed: {redis_stats['jobs_deleted']}, "
            f"pending markers removed: {redis_stats['pending_deleted']}"
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(f"✗ Failed to clear Redis: {exc}")
        raise
    
    click.echo("Clearing Elasticsearch documents...")
    try:
        es_client.clear_all_documents()
        click.echo("  ✓ Elasticsearch indices cleared and recreated")
    except Exception as exc:  # noqa: BLE001
        click.echo(f"✗ Failed to clear Elasticsearch documents: {exc}")
        raise


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
@click.option("--assets-dir", default="assets", show_default=True, help="Directory containing test documents")
def integration_test(base_url, timeout, assets_dir):
    """Run integration tests against the API service using prepared assets."""
    import time
    import uuid
    from datetime import datetime, timezone
    from pathlib import Path

    import httpx

    click.echo(f"Running integration tests against {base_url}")
    click.echo(f"Using assets from {assets_dir}")
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

    assets_path = Path(assets_dir)
    if not assets_path.exists():
        click.echo(f"Error: Assets directory '{assets_dir}' not found.")
        raise SystemExit(1)

    run_suffix = uuid.uuid4().hex[:6]
    doc_groups = {}
    all_docs = []

    for group_dir in sorted(assets_path.iterdir()):
        if not group_dir.is_dir() or not group_dir.name.startswith("doc_group"):
            continue
        docs: list[dict[str, str]] = []
        for file_path in sorted(group_dir.glob("*.txt")):
            content = file_path.read_text(encoding="utf-8")
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            title = lines[0] if lines else file_path.stem
            if len(title) > 120:
                title = f"{title[:117]}..."
            article_id = f"it_{run_suffix}_{group_dir.name}_{file_path.stem}"
            doc_info = {
                "article_id": article_id,
                "title": title,
                "content": content,
                "group": group_dir.name,
                "file_path": str(file_path),
            }
            docs.append(doc_info)
            all_docs.append(doc_info)
        if docs:
            doc_groups[group_dir.name] = docs

    if not all_docs:
        click.echo("No document groups found in assets directory.")
        raise SystemExit(1)

    status_poll_timeout = 90
    status_poll_interval = 2

    try:
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            # Health check
            resp = None
            try:
                resp = client.get("/api/v1/system/health")
                resp.raise_for_status()
                data = resp.json()
                record("Health endpoint", True, f"status={data.get('status')}")
            except Exception as exc:  # noqa: BLE001
                detail = format_error(resp, exc)
                record("Health endpoint", False, detail)
                raise SystemExit(1)

            # Submit articles
            click.echo("Submitting articles...")
            for group_name, docs in doc_groups.items():
                click.echo(f"\nProcessing group: {group_name}")
                for doc in docs:
                    payload = {
                        "article_id": doc["article_id"],
                        "title": doc["title"],
                        "content": doc["content"],
                        "publish_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        "source": "integration_test_assets",
                        "state": 1,
                        "top": 0,
                        "tags": [{"id": 9999, "name": "test"}],
                        "topic": [{"id": "topic_integration", "name": "integration"}],
                    }
                    resp = None
                    try:
                        resp = client.post("/api/v1/articles/", json=payload)
                        resp.raise_for_status()
                        record(f"Submit {doc['article_id']}", True)
                    except Exception as exc:  # noqa: BLE001
                        detail = format_error(resp, exc)
                        record(f"Submit {doc['article_id']}", False, detail)

            # Poll until worker completes
            click.echo("\nWaiting for worker completion...")
            pending = {doc["article_id"]: doc for doc in all_docs}
            article_cache = {}
            deadline = time.time() + status_poll_timeout

            while pending and time.time() < deadline:
                progress = False
                for article_id in list(pending.keys()):
                    resp = None
                    try:
                        resp = client.get(f"/api/v1/articles/{article_id}")
                        resp.raise_for_status()
                        payload = resp.json()
                        article_data = payload.get("article", {})
                        status_value = article_data.get("cluster_status")
                        if status_value and status_value != "pending":
                            detail = f"status={status_value} cluster={article_data.get('cluster_id')}"
                            record(f"Article status {article_id}", True, detail)
                            article_cache[article_id] = payload
                            pending.pop(article_id)
                            progress = True
                    except Exception as exc:  # noqa: BLE001
                        detail = format_error(resp, exc)
                        record(f"Article status {article_id}", False, detail)
                        pending.pop(article_id)
                if pending and not progress:
                    time.sleep(status_poll_interval)

            for article_id in list(pending.keys()):
                record(f"Article status {article_id}", False, "timeout waiting for worker")
                pending.pop(article_id)

            # Verify similar articles endpoint
            for doc in all_docs:
                article_id = doc["article_id"]
                if article_id not in article_cache:
                    continue
                expected_peers = {
                    peer["article_id"]
                    for peer in doc_groups.get(doc["group"], [])
                    if peer["article_id"] != article_id
                }
                resp = None
                try:
                    resp = client.get(f"/api/v1/articles/{article_id}/similar")
                    resp.raise_for_status()
                    data = resp.json()
                    similar_items = data.get("articles", [])
                    found_ids = {item.get("article_id") for item in similar_items}
                    found_count = sum(1 for peer in expected_peers if peer in found_ids)
                    detail = f"found {found_count}/{len(expected_peers)} expected peers"
                    success = found_count == len(expected_peers)
                    record(f"Similar articles {article_id}", success, detail)
                except Exception as exc:  # noqa: BLE001
                    detail = format_error(resp, exc)
                    record(f"Similar articles {article_id}", False, detail)

            # Verify cluster detail endpoint
            cluster_members = {}
            for payload in article_cache.values():
                article_data = payload.get("article", {})
                cluster_id = article_data.get("cluster_id")
                if not cluster_id:
                    continue
                cluster_members.setdefault(cluster_id, set()).add(article_data.get("article_id"))

            for cluster_id, members in cluster_members.items():
                resp = None
                try:
                    resp = client.get(
                        f"/api/v1/clusters/{cluster_id}",
                        params={"include_articles": "true"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    articles = data.get("articles") or []
                    returned_ids = {article.get("article_id") for article in articles}
                    success = members.issubset(returned_ids)
                    detail = f"cluster size={len(returned_ids)} expected_members={len(members)}"
                    record(f"Cluster detail {cluster_id}", success, detail)
                except Exception as exc:  # noqa: BLE001
                    detail = format_error(resp, exc)
                    record(f"Cluster detail {cluster_id}", False, detail)

            # Verify article search endpoint
            for doc in all_docs:
                article_id = doc["article_id"]
                resp = None
                try:
                    resp = client.get(
                        "/api/v1/clusters/",
                        params={"title": doc["title"], "page_size": 50},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    items = data.get("items", [])
                    ids = {item.get("article_id") for item in items}
                    success = article_id in ids
                    detail = f"found={success} total_items={len(items)}"
                    record(f"Article search {article_id}", success, detail)
                except Exception as exc:  # noqa: BLE001
                    detail = format_error(resp, exc)
                    record(f"Article search {article_id}", False, detail)

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
