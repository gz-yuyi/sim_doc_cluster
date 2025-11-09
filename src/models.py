"""Data models for the document similarity clustering system."""

from datetime import datetime
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ArticleCreate(BaseModel):
    """Model for creating a new article."""
    
    article_id: str = Field(..., description="Unique identifier for the article")
    title: str = Field(..., description="Article title")
    content: str = Field(..., max_length=200000, description="Article content (max 200k chars)")
    publish_time: datetime = Field(..., description="Publication time")
    source: str = Field(..., description="Source of the article")
    language: str = Field(default="zh-CN", description="Article language")
    metadata: Optional[Dict[str, Union[str, int, float, bool]]] = Field(
        default=None, description="Additional metadata"
    )


class Article(BaseModel):
    """Model for an article with similarity information."""
    
    article_id: str
    title: str
    publish_time: datetime
    source: str
    cluster_id: Optional[str] = None
    cluster_status: str = Field(default="pending", description="pending/matched/unique")
    similarity_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime
    updated_at: datetime


class ArticleResponse(BaseModel):
    """Response model for article queries."""
    
    article: Article
    cluster: Optional["Cluster"] = None
    trace_id: str


class Cluster(BaseModel):
    """Model for a cluster of similar articles."""
    
    cluster_id: str
    article_ids: List[str]
    size: int
    representative_article_id: str
    last_updated: datetime
    top_terms: Optional[List[Dict[str, Union[str, float]]]] = None


class ClusterResponse(BaseModel):
    """Response model for cluster queries."""
    
    cluster: Cluster
    articles: Optional[List[Article]] = None
    trace_id: str


class ClusterListResponse(BaseModel):
    """Response model for cluster list queries."""
    
    clusters: List[Dict[str, Union[str, int, datetime]]]
    pagination: Dict[str, Union[int, str]]
    trace_id: str


class SimilarArticlesResponse(BaseModel):
    """Response model for similar articles queries."""
    
    cluster_id: str
    articles: List[Dict[str, Union[str, float]]]
    trace_id: str


class ArticleSubmissionResponse(BaseModel):
    """Response model for article submission."""
    
    article_id: str
    cluster_status: str
    cluster_id: Optional[str] = None
    candidate_cluster_id: Optional[str] = None
    finalize_eta_ms: int = Field(default=120, description="Estimated processing time in ms")
    trace_id: str


class RecheckRequest(BaseModel):
    """Request model for article recheck."""
    
    article_ids: List[str] = Field(..., min_items=1, max_items=100)
    reason: str = Field(default="manual_review", description="Reason for recheck")


class RecheckResponse(BaseModel):
    """Response model for article recheck."""
    
    accepted: bool
    job_id: str
    trace_id: str


class HealthCheckResponse(BaseModel):
    """Response model for health check."""
    
    status: str = Field(..., pattern="^(pass|warn|fail)$")
    components: Dict[str, str]
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Error response model."""
    
    error: Dict[str, str]
    trace_id: str


class SimilarityJob(BaseModel):
    """Model for similarity calculation job."""
    
    job_id: str
    article_id: str
    shingles: List[str]
    candidates: List[Dict[str, str]]
    created_at: datetime
    status: str = "pending"


class ArticleFeatures(BaseModel):
    """Model for article features used in similarity calculation."""
    
    article_id: str
    simhash: str
    minhash_signature: List[str]
    shingles: List[str]
    extracted_at: datetime


# Update forward references
ArticleResponse.model_rebuild()
ClusterResponse.model_rebuild()