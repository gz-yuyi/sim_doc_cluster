"""FastAPI routes and API endpoints for the document similarity clustering system."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings
from src.models import ArticleCreate, ArticleSearchPage, ArticleSearchResponse, RecheckRequest
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


@cluster_router.get("/", response_model=ArticleSearchPage)
@cluster_router.get("", response_model=ArticleSearchPage, include_in_schema=False)
async def search_articles(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    sort: Optional[str] = Query(default=None, description="Sort field and order"),
    state: Optional[int] = Query(default=None, ge=0, le=2, description="Article state"),
    top: Optional[int] = Query(default=None, ge=0, le=1, description="Pinned flag"),
    title: Optional[str] = Query(default=None, description="Title keyword for fuzzy search"),
    source: Optional[str] = Query(default=None, description="Source platform ID or name"),
    start_time: Optional[datetime] = Query(default=None, description="Start publish time"),
    end_time: Optional[datetime] = Query(default=None, description="End publish time"),
    tag_id: Optional[str] = Query(default=None, description="Primary tag ID"),
    topic: Optional[List[str]] = Query(default=None, description="Topic IDs (multi-select)")
):
    """Search articles by metadata and return matching article IDs."""
    trace_id = generate_trace_id()
    
    try:
        # Some clients incorrectly send filters in the body of a GET request (e.g. form-data in Postman).
        # To keep the endpoint usable, merge query params with any body payload while still validating values.
        body_params: Dict[str, Any] = {}
        try:
            body_bytes = await request.body()
            if body_bytes:
                content_type = (request.headers.get("content-type") or "").lower()
                if "application/json" in content_type:
                    body_params = await request.json()
                elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
                    form_data = await request.form()
                    body_params = dict(form_data)
        except Exception:
            # Ignore body parsing errors for GET; rely on validated query params instead.
            body_params = {}

        def pick_int(
            name: str,
            current: Optional[int],
            minimum: Optional[int] = None,
            maximum: Optional[int] = None
        ) -> Optional[int]:
            if name not in body_params:
                return current
            raw = body_params.get(name)
            if raw in (None, ""):
                return current
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid {name}: expected integer")
            if minimum is not None and value < minimum:
                raise ValueError(f"{name} must be >= {minimum}")
            if maximum is not None and value > maximum:
                raise ValueError(f"{name} must be <= {maximum}")
            return value

        def pick_str(name: str, current: Optional[str]) -> Optional[str]:
            if name not in body_params:
                return current
            raw = body_params.get(name)
            if raw is None:
                return None
            value = str(raw).strip()
            return value or None

        def pick_datetime(name: str, current: Optional[datetime]) -> Optional[datetime]:
            if name not in body_params:
                return current
            raw = body_params.get(name)
            if raw in (None, ""):
                return None
            if isinstance(raw, datetime):
                return raw
            if isinstance(raw, str):
                value = raw.strip()
                if not value:
                    return None
                normalized = value.replace(" ", "T")
                if normalized.endswith("Z"):
                    normalized = normalized[:-1] + "+00:00"
                try:
                    return datetime.fromisoformat(normalized)
                except ValueError:
                    raise ValueError(f"Invalid {name}: expected ISO8601 datetime string")
            raise ValueError(f"Invalid {name}: unsupported type")

        def pick_list(name: str, current: Optional[List[str]]) -> Optional[List[str]]:
            if name not in body_params:
                return current
            raw = body_params.get(name)
            if raw in (None, ""):
                return None
            if isinstance(raw, list):
                values = [str(item).strip() for item in raw if str(item).strip()]
            else:
                values = [part.strip() for part in str(raw).split(",") if part.strip()]
            return values or None

        page = pick_int("page", page, minimum=1)
        page_size = pick_int("page_size", page_size, minimum=1, maximum=100)
        sort = pick_str("sort", sort)
        state = pick_int("state", state, minimum=0, maximum=2)
        top = pick_int("top", top, minimum=0, maximum=1)
        title = pick_str("title", title)
        source = pick_str("source", source)
        start_time = pick_datetime("start_time", start_time)
        end_time = pick_datetime("end_time", end_time)
        tag_id = pick_str("tag_id", tag_id)
        topic = pick_list("topic", topic)

        # First, fetch base article documents for the search
        search_result = cluster_service.search_articles(
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
        
        articles = search_result.get("items", [])
        total = search_result.get("total", 0)
        total_pages = search_result.get("total_pages", 0)
        
        # Collect all cluster IDs present in the result set for batch hydration
        cluster_ids = {
            article.get("cluster_id")
            for article in articles
            if article.get("cluster_id")
        }
        
        # Preload articles for each cluster to avoid repeated queries
        cluster_articles_map: Dict[str, List[Dict[str, Any]]] = {}
        for cluster_id in cluster_ids:
            cluster_articles_map[cluster_id] = cluster_service.es.search_articles_by_cluster(cluster_id)
        
        # Build response: for each article, include all other article IDs in the same cluster
        results: List[ArticleSearchResponse] = []
        for article in articles:
            article_id = article["article_id"]
            cluster_id = article.get("cluster_id")
            similar_ids: List[str] = [article_id]
            if cluster_id and cluster_id in cluster_articles_map:
                similar_ids.extend(
                    a["article_id"]
                    for a in cluster_articles_map[cluster_id]
                    if a["article_id"] != article_id
                )
            results.append(
                ArticleSearchResponse(
                    article_id=article_id,
                    similar_article_ids=similar_ids,
                )
            )
        
        return ArticleSearchPage(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            items=results
        )
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
