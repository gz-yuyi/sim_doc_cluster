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
    
    # Create and configure app
    app = create_app()
    
    # Start server
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        reload=reload,
        log_level="debug" if settings.debug else "info"
    )


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


@cli.command()
@click.option("--timeout", default=5, type=int, help="Connection timeout in seconds")
def check_external_service(timeout):
    """Check external service connectivity and status."""
    import time
    from datetime import datetime
    
    click.echo("Checking external services...")
    click.echo(f"Timeout: {timeout} seconds")
    click.echo("-" * 50)
    
    all_ok = True
    
    # Check Elasticsearch
    click.echo("🔍 Checking Elasticsearch...")
    try:
        start_time = time.time()
        if es_client.ping():
            response_time = (time.time() - start_time) * 1000
            click.echo(f"✅ Elasticsearch: OK (response time: {response_time:.2f}ms)")
            
            # Check indices
            try:
                articles_exists = es_client.client.indices.exists(index=settings.es_articles_index_full)
                clusters_exists = es_client.client.indices.exists(index=settings.es_clusters_index_full)
                
                if articles_exists:
                    click.echo(f"   Articles index '{settings.es_articles_index_full}': exists")
                else:
                    click.echo(f"   Articles index '{settings.es_articles_index_full}': missing")
                    all_ok = False
                
                if clusters_exists:
                    click.echo(f"   Clusters index '{settings.es_clusters_index_full}': exists")
                else:
                    click.echo(f"   Clusters index '{settings.es_clusters_index_full}': missing")
                    all_ok = False
                    
            except Exception as e:
                click.echo(f"   Index check failed: {e}")
                all_ok = False
                
        else:
            click.echo("❌ Elasticsearch: FAILED (connection refused)")
            all_ok = False
    except Exception as e:
        click.echo(f"❌ Elasticsearch: ERROR - {e}")
        all_ok = False
    
    click.echo()
    
    # Check Redis
    click.echo("🔍 Checking Redis...")
    try:
        start_time = time.time()
        if redis_client.ping():
            response_time = (time.time() - start_time) * 1000
            click.echo(f"✅ Redis: OK (response time: {response_time:.2f}ms)")
            
            # Get queue stats
            try:
                stats = redis_client.get_queue_stats()
                click.echo(f"   Queue length: {stats['queue_length']}")
                click.echo(f"   Pending jobs: {stats['pending_jobs']}")
                click.echo(f"   Processing jobs: {stats['processing_jobs']}")
            except Exception as e:
                click.echo(f"   Queue stats failed: {e}")
                
        else:
            click.echo("❌ Redis: FAILED (connection refused)")
            all_ok = False
    except Exception as e:
        click.echo(f"❌ Redis: ERROR - {e}")
        all_ok = False
    
    click.echo()
    
    # Check configuration
    click.echo("🔍 Checking Configuration...")
    try:
        click.echo(f"   ES URL: {settings.es_url}")
        click.echo(f"   Redis URL: {settings.redis_url}")
        click.echo(f"   Similarity Threshold: {settings.similarity_threshold}")
        click.echo(f"   Articles Index: {settings.es_articles_index_full}")
        click.echo(f"   Clusters Index: {settings.es_clusters_index_full}")
        click.echo(f"   Queue Name: {settings.redis_queue_name}")
    except Exception as e:
        click.echo(f"❌ Configuration check failed: {e}")
        all_ok = False
    
    click.echo()
    click.echo("-" * 50)
    
    if all_ok:
        click.echo("✅ All external services are running correctly")
        click.echo(f"   Checked at: {datetime.utcnow().isoformat()}")
    else:
        click.echo("❌ Some services have issues")
        click.echo("   Please check the errors above and fix them")
        click.echo("   Run 'uv run python main.py init' to create missing indices")
    
    return 0 if all_ok else 1


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
