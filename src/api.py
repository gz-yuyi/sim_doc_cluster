"""FastAPI routes and API endpoints for the document similarity clustering system."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings
from src.models import ArticleCreate, ArticleSearchResponse, RecheckRequest
from src.services import article_service, cluster_service, health_service
from src.utils import generate_trace_id, raise_http_exception, validate_article_id, validate_cluster_id


# Create API router
api_router = APIRouter(prefix=settings.api_v1_prefix)

# Article endpoints
article_router = APIRouter(prefix="/articles", tags=["articles"])


@article_router.post("/", response_model=dict)
async def submit_article(article: ArticleCreate):
    """Submit a new article for similarity processing."""
    trace_id = generate_trace_id()
    
    # Validate article ID
    if not validate_article_id(article.article_id):
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_ARGUMENT",
            message=f"Invalid article_id: {article.article_id}",
            trace_id=trace_id
        )
    
    # Validate content length
    if len(article.content) > 200000:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_ARGUMENT",
            message="Article content exceeds maximum length of 200,000 characters",
            trace_id=trace_id
        )
    
    try:
        article_service.submit_article(article)
        return {}
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_ERROR",
            message=f"Failed to submit article: {str(e)}",
            trace_id=trace_id
        )


@article_router.get("/{article_id}", response_model=dict)
async def get_article(article_id: str):
    """Get article details with cluster information."""
    trace_id = generate_trace_id()
    
    # Validate article ID
    if not validate_article_id(article_id):
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_ARGUMENT",
            message=f"Invalid article_id: {article_id}",
            trace_id=trace_id
        )
    
    response = article_service.get_article(article_id)
    if not response:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="ARTICLE_NOT_FOUND",
            message=f"Article not found: {article_id}",
            trace_id=trace_id
        )
    
    return response.dict()


@article_router.get("/{article_id}/similar", response_model=dict)
async def get_similar_articles(article_id: str):
    """Get similar articles for a given article."""
    trace_id = generate_trace_id()
    
    # Validate article ID
    if not validate_article_id(article_id):
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_ARGUMENT",
            message=f"Invalid article_id: {article_id}",
            trace_id=trace_id
        )
    
    response = article_service.get_similar_articles(article_id)
    if not response:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="CLUSTER_PENDING",
            message="Article similarity processing is not yet complete",
            trace_id=trace_id
        )
    
    return response.dict()


@article_router.post("/recheck", response_model=dict)
async def recheck_articles(request: RecheckRequest):
    """Trigger recheck for specified articles."""
    trace_id = generate_trace_id()
    
    # Validate article IDs
    for article_id in request.article_ids:
        if not validate_article_id(article_id):
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_ARGUMENT",
                message=f"Invalid article_id: {article_id}",
                trace_id=trace_id
            )
    
    try:
        response = article_service.recheck_articles(request.article_ids, request.reason)
        return response.dict()
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_ERROR",
            message=f"Failed to trigger recheck: {str(e)}",
            trace_id=trace_id
        )


# Cluster endpoints
cluster_router = APIRouter(prefix="/clusters", tags=["clusters"])


@cluster_router.get("/{cluster_id}", response_model=dict)
async def get_cluster(
    cluster_id: str,
    include_articles: bool = Query(default=False, description="Include all articles in the cluster")
):
    """Get cluster details."""
    trace_id = generate_trace_id()
    
    # Validate cluster ID
    if not validate_cluster_id(cluster_id):
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_ARGUMENT",
            message=f"Invalid cluster_id: {cluster_id}",
            trace_id=trace_id
        )
    
    response = cluster_service.get_cluster(cluster_id, include_articles)
    if not response:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="CLUSTER_NOT_FOUND",
            message=f"Cluster not found: {cluster_id}",
            trace_id=trace_id
        )
    
    return response.dict()


@cluster_router.get("/", response_model=ArticleSearchResponse)
async def search_articles(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    sort: Optional[str] = Query(default=None, description="Sort field and order"),
    state: Optional[int] = Query(default=None, ge=0, le=2, description="Article state"),
    top: Optional[int] = Query(default=None, ge=0, le=1, description="Pinned flag"),
    title: Optional[str] = Query(default=None, description="Title keyword for fuzzy search"),
    source: Optional[int] = Query(default=None, description="Source platform ID"),
    start_time: Optional[datetime] = Query(default=None, description="Start publish time"),
    end_time: Optional[datetime] = Query(default=None, description="End publish time"),
    tag_id: Optional[str] = Query(default=None, description="Primary tag ID"),
    topic: Optional[List[str]] = Query(default=None, description="Topic IDs (multi-select)")
):
    """Search articles by metadata and return matching article IDs."""
    trace_id = generate_trace_id()
    
    try:
        article_ids = cluster_service.search_articles(
            page=page,
            page_size=page_size,
            sort=sort,
            state=state,
            top=top,
            title=title,
            source=str(source) if source is not None else None,
            start_time=start_time.isoformat() if start_time else None,
            end_time=end_time.isoformat() if end_time else None,
            tag_id=tag_id,
            topic_ids=topic
        )
        return {
            "article_ids": article_ids,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": len(article_ids),
                "pages": (len(article_ids) + page_size - 1) // page_size
            }
        }
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_ARGUMENT",
            message=str(e),
            trace_id=trace_id
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_ERROR",
            message=f"Failed to search articles: {str(e)}",
            trace_id=trace_id
        )


# System endpoints
system_router = APIRouter(prefix="/system", tags=["system"])


@system_router.get("/health", response_model=dict)
async def health_check():
    """Check system health."""
    try:
        response = health_service.check_health()
        return response.dict()
    except Exception as e:
        return {
            "status": "fail",
            "components": {
                "elasticsearch": "fail",
                "redis": "fail",
                "worker": "fail"
            },
            "timestamp": response.timestamp if 'response' in locals() else None,
            "error": str(e)
        }


# Include all routers
api_router.include_router(article_router)
api_router.include_router(cluster_router)
api_router.include_router(system_router)


def setup_cors(app):
    """Setup CORS middleware."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def create_app():
    """Create FastAPI application."""
    from fastapi import FastAPI
    
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Document Similarity Clustering System API",
        docs_url="/docs",
        redoc_url="/redoc"
    )
    
    # Setup CORS
    setup_cors(app)
    
    # Include API router
    app.include_router(api_router)
    
    # Add exception handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        content = {
            "error": {
                "code": exc.detail.get("error", {}).get("code", "UNKNOWN_ERROR"),
                "message": exc.detail.get("error", {}).get("message", "Unknown error")
            },
            "trace_id": exc.detail.get("trace_id", "unknown")
        }
        return JSONResponse(status_code=exc.status_code, content=content)
    
    return app
