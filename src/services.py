"""Business logic services for the document similarity clustering system."""

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Set

from src.config import settings
from src.es_client import es_client
from src.models import (
    Article, ArticleCreate, Cluster, ArticleSubmissionResponse,
    ArticleResponse, SimilarArticlesResponse, ClusterResponse,
    ClusterListResponse, RecheckResponse, HealthCheckResponse
)
from src.redis_client import redis_client
from src.similarity import similarity_calculator


class ArticleService:
    """Service for article management and similarity processing."""
    
    def __init__(self):
        """Initialize article service."""
        self.es = es_client
        self.redis = redis_client
        self.similarity = similarity_calculator
    
    def submit_article(self, article_data: ArticleCreate) -> ArticleSubmissionResponse:
        """Submit a new article for similarity processing."""
        trace_id = str(uuid.uuid4())
        
        # Check if article already exists
        existing_article = self.es.get_article(article_data.article_id)
        if existing_article:
            return ArticleSubmissionResponse(
                article_id=article_data.article_id,
                cluster_status=existing_article.get("cluster_status", "pending"),
                cluster_id=existing_article.get("cluster_id"),
                candidate_cluster_id=existing_article.get("cluster_id"),
                finalize_eta_ms=0,
                trace_id=trace_id
            )
        
        # Prepare full text for feature extraction
        full_text = f"{article_data.title} {article_data.content}"
        
        # Extract features
        features = self.similarity.extractor.extract_features(full_text)
        
        # Check for exact duplicates using SimHash
        exact_duplicates = self.es.search_simhash(features["simhash"])
        
        if exact_duplicates:
            # Found exact duplicate, assign to same cluster
            duplicate_article = exact_duplicates[0]
            cluster_id = duplicate_article.get("cluster_id")
            
            # Create article document
            article_doc = {
                "article_id": article_data.article_id,
                "title": article_data.title,
                "content": article_data.content,
                "publish_time": article_data.publish_time.isoformat(),
                "source": article_data.source,
                "language": article_data.language,
                "metadata": article_data.metadata or {},
                "simhash": features["simhash"],
                "minhash_signature": features["minhash_signature"],
                "cluster_id": cluster_id,
                "cluster_status": "matched",
                "similarity_score": 1.0,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            # Index article
            self.es.index_article(article_doc)
            
            return ArticleSubmissionResponse(
                article_id=article_data.article_id,
                cluster_status="matched",
                cluster_id=cluster_id,
                candidate_cluster_id=cluster_id,
                finalize_eta_ms=0,
                trace_id=trace_id
            )
        
        # Search for candidates using MinHash LSH
        candidates = self.es.search_minhash_candidates(features["minhash_signature"])
        
        # Prepare candidates for similarity calculation
        candidate_data = []
        for candidate in candidates:
            if candidate["article_id"] != article_data.article_id:
                candidate_data.append({
                    "article_id": candidate["article_id"],
                    "cluster_id": candidate.get("cluster_id"),
                    "shingles": candidate.get("shingles", []),
                    "simhash": candidate.get("simhash")
                })
        
        # Calculate similarity
        similarity_result = self.similarity.calculate_article_similarity(full_text, candidate_data)
        
        # Create article document
        article_doc = {
            "article_id": article_data.article_id,
            "title": article_data.title,
            "content": article_data.content,
            "publish_time": article_data.publish_time.isoformat(),
            "source": article_data.source,
            "language": article_data.language,
            "metadata": article_data.metadata or {},
            "simhash": features["simhash"],
            "minhash_signature": features["minhash_signature"],
            "shingles": features["shingles"],
            "cluster_id": None,
            "cluster_status": "pending",
            "similarity_score": None,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Index article
        self.es.index_article(article_doc)
        
        # Determine candidate cluster
        candidate_cluster_id = None
        if similarity_result["status"] == "similar":
            candidate_cluster_id = self.similarity.find_best_cluster(similarity_result["similar_articles"])
        
        # Set pending cluster information
        self.redis.set_pending_cluster(
            article_data.article_id,
            candidate_cluster_id,
            eta_ms=120
        )
        
        # Enqueue similarity job
        job_data = {
            "article_id": article_data.article_id,
            "shingles": features["shingles"],
            "candidates": candidate_data
        }
        job_id = self.redis.enqueue_similarity_job(job_data)
        
        return ArticleSubmissionResponse(
            article_id=article_data.article_id,
            cluster_status="pending",
            cluster_id=None,
            candidate_cluster_id=candidate_cluster_id,
            finalize_eta_ms=120,
            trace_id=trace_id
        )
    
    def get_article(self, article_id: str) -> Optional[ArticleResponse]:
        """Get article details with cluster information."""
        trace_id = str(uuid.uuid4())
        
        # Get article from Elasticsearch
        article_data = self.es.get_article(article_id)
        if not article_data:
            return None
        
        # Convert to Article model
        article = Article(
            article_id=article_data["article_id"],
            title=article_data["title"],
            publish_time=datetime.fromisoformat(article_data["publish_time"]),
            source=article_data["source"],
            cluster_id=article_data.get("cluster_id"),
            cluster_status=article_data.get("cluster_status", "pending"),
            similarity_score=article_data.get("similarity_score"),
            created_at=datetime.fromisoformat(article_data["created_at"]),
            updated_at=datetime.fromisoformat(article_data["updated_at"])
        )
        
        # Get cluster information if available
        cluster = None
        if article.cluster_id:
            cluster_data = self.es.get_cluster(article.cluster_id)
            if cluster_data:
                cluster = Cluster(
                    cluster_id=cluster_data["cluster_id"],
                    article_ids=cluster_data["article_ids"],
                    size=cluster_data["size"],
                    representative_article_id=cluster_data["representative_article_id"],
                    last_updated=datetime.fromisoformat(cluster_data["last_updated"]),
                    top_terms=cluster_data.get("top_terms")
                )
        
        return ArticleResponse(
            article=article,
            cluster=cluster,
            trace_id=trace_id
        )
    
    def get_similar_articles(self, article_id: str) -> Optional[SimilarArticlesResponse]:
        """Get similar articles for a given article."""
        trace_id = str(uuid.uuid4())
        
        # Get article
        article_data = self.es.get_article(article_id)
        if not article_data:
            return None
        
        # Check if article is still pending
        if article_data.get("cluster_status") == "pending":
            return None
        
        # If article has no cluster, no similar articles
        cluster_id = article_data.get("cluster_id")
        if not cluster_id:
            return None
        
        # Get all articles in the cluster
        cluster_articles = self.es.search_articles_by_cluster(cluster_id)
        
        # Prepare response
        articles = []
        for cluster_article in cluster_articles:
            if cluster_article["article_id"] != article_id:
                articles.append({
                    "article_id": cluster_article["article_id"],
                    "title": cluster_article["title"],
                    "similarity_score": cluster_article.get("similarity_score", 0.0)
                })
        
        return SimilarArticlesResponse(
            cluster_id=cluster_id,
            articles=articles,
            trace_id=trace_id
        )
    
    def recheck_articles(self, article_ids: List[str], reason: str) -> RecheckResponse:
        """Trigger recheck for specified articles."""
        trace_id = str(uuid.uuid4())
        job_id = f"recheck_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        
        # Process each article
        for article_id in article_ids:
            # Get article
            article_data = self.es.get_article(article_id)
            if not article_data:
                continue
            
            # Reset cluster status
            self.es.update_article(article_id, {
                "cluster_status": "pending",
                "cluster_id": None,
                "similarity_score": None,
                "updated_at": datetime.utcnow().isoformat()
            })
            
            # Prepare full text for feature extraction
            full_text = f"{article_data['title']} {article_data['content']}"
            
            # Extract features
            features = self.similarity.extractor.extract_features(full_text)
            
            # Update article with new features
            self.es.update_article(article_id, {
                "simhash": features["simhash"],
                "minhash_signature": features["minhash_signature"],
                "shingles": features["shingles"]
            })
            
            # Search for candidates
            candidates = self.es.search_minhash_candidates(features["minhash_signature"])
            
            # Prepare candidates for similarity calculation
            candidate_data = []
            for candidate in candidates:
                if candidate["article_id"] != article_id:
                    candidate_data.append({
                        "article_id": candidate["article_id"],
                        "cluster_id": candidate.get("cluster_id"),
                        "shingles": candidate.get("shingles", []),
                        "simhash": candidate.get("simhash")
                    })
            
            # Enqueue similarity job
            job_data = {
                "article_id": article_id,
                "shingles": features["shingles"],
                "candidates": candidate_data
            }
            self.redis.enqueue_similarity_job(job_data)
        
        return RecheckResponse(
            accepted=True,
            job_id=job_id,
            trace_id=trace_id
        )


class ClusterService:
    """Service for cluster management."""
    
    def __init__(self):
        """Initialize cluster service."""
        self.es = es_client
    
    def get_cluster(self, cluster_id: str, include_articles: bool = False) -> Optional[ClusterResponse]:
        """Get cluster details."""
        trace_id = str(uuid.uuid4())
        
        # Get cluster from Elasticsearch
        cluster_data = self.es.get_cluster(cluster_id)
        if not cluster_data:
            return None
        
        # Convert to Cluster model
        cluster = Cluster(
            cluster_id=cluster_data["cluster_id"],
            article_ids=cluster_data["article_ids"],
            size=cluster_data["size"],
            representative_article_id=cluster_data["representative_article_id"],
            last_updated=datetime.fromisoformat(cluster_data["last_updated"]),
            top_terms=cluster_data.get("top_terms")
        )
        
        # Get articles if requested
        articles = None
        if include_articles:
            cluster_articles = self.es.search_articles_by_cluster(cluster_id)
            articles = []
            for article_data in cluster_articles:
                article = Article(
                    article_id=article_data["article_id"],
                    title=article_data["title"],
                    publish_time=datetime.fromisoformat(article_data["publish_time"]),
                    source=article_data["source"],
                    cluster_id=article_data.get("cluster_id"),
                    cluster_status=article_data.get("cluster_status", "pending"),
                    similarity_score=article_data.get("similarity_score"),
                    created_at=datetime.fromisoformat(article_data["created_at"]),
                    updated_at=datetime.fromisoformat(article_data["updated_at"])
                )
                articles.append(article)
        
        return ClusterResponse(
            cluster=cluster,
            articles=articles,
            trace_id=trace_id
        )
    
    def list_clusters(self, page: int = 1, page_size: int = 20, min_size: int = 2,
                     max_age_minutes: Optional[int] = None, sort: str = "last_updated:desc") -> ClusterListResponse:
        """List clusters with pagination and filtering."""
        trace_id = str(uuid.uuid4())
        
        # Get clusters from Elasticsearch
        result = self.es.list_clusters(
            page=page,
            page_size=page_size,
            min_size=min_size,
            max_age_minutes=max_age_minutes,
            sort=sort
        )
        
        return ClusterListResponse(
            clusters=result["clusters"],
            pagination={
                "page": result["page"],
                "page_size": result["page_size"],
                "total": result["total"]
            },
            trace_id=trace_id
        )


class HealthService:
    """Service for system health monitoring."""
    
    def __init__(self):
        """Initialize health service."""
        self.es = es_client
        self.redis = redis_client
    
    def check_health(self) -> HealthCheckResponse:
        """Check system health."""
        timestamp = datetime.utcnow()
        components = {}
        overall_status = "pass"
        
        # Check Elasticsearch
        if self.es.ping():
            components["elasticsearch"] = "pass"
        else:
            components["elasticsearch"] = "fail"
            overall_status = "fail"
        
        # Check Redis
        redis_health = self.redis.health_check()
        components["redis"] = redis_health["redis"]
        if redis_health["redis"] != "pass":
            overall_status = "fail"
        
        # Check worker (queue length)
        queue_stats = self.redis.get_queue_stats()
        if queue_stats["queue_length"] > 1000:  # Arbitrary threshold
            components["worker"] = "warn"
            if overall_status == "pass":
                overall_status = "warn"
        else:
            components["worker"] = "pass"
        
        return HealthCheckResponse(
            status=overall_status,
            components=components,
            timestamp=timestamp
        )


# Global service instances
article_service = ArticleService()
cluster_service = ClusterService()
health_service = HealthService()