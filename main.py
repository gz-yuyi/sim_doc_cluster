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


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
