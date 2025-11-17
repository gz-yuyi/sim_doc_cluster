"""Data models for the document similarity clustering system."""

from datetime import datetime
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ArticleTag(BaseModel):
    """Tag attached to an article."""
    
    id: int = Field(..., description="Tag identifier")
    name: str = Field(..., description="Tag name")


class ArticleTopic(BaseModel):
    """Topic attached to an article."""
    
    id: str = Field(..., description="Topic identifier")
    name: str = Field(..., description="Topic label")


class ArticleCreate(BaseModel):
    """Model for creating a new article."""
    
    article_id: str = Field(..., description="Unique identifier for the article")
    title: str = Field(..., description="Article title")
    content: str = Field(..., max_length=200000, description="Article content (max 200k chars)")
    publish_time: datetime = Field(..., description="Publication time")
    source: str = Field(..., description="Source of the article")
    state: int = Field(..., ge=0, le=2, description="Article visibility state (0,1,2)")
    top: int = Field(..., ge=0, le=1, description="Whether the article is pinned (0/1)")
    tags: List[ArticleTag] = Field(default_factory=list, description="List of tags")
    topic: List[ArticleTopic] = Field(default_factory=list, description="List of topics")


class Article(BaseModel):
    """Model for an article with similarity information."""
    
    article_id: str
    title: str
    publish_time: datetime
    source: str
    state: int = Field(default=1, description="Article visibility state")
    top: int = Field(default=0, description="Pin flag")
    tags: List[ArticleTag] = Field(default_factory=list)
    topic: List[ArticleTopic] = Field(default_factory=list)
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


class SimilarArticlesResponse(BaseModel):
    """Response model for similar articles queries."""
    
    cluster_id: str
    articles: List[Dict[str, Union[str, float]]]
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


class ArticleSearchResponse(BaseModel):
    """Response for article search endpoint."""
    
    article_ids: List[str]
    pagination: Dict[str, int]
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "article_ids": ["article_123", "article_456"],
                    "pagination": {
                        "page": 1,
                        "page_size": 20,
                        "total": 2,
                        "pages": 1
                    }
                }
            ]
        }
    }


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
