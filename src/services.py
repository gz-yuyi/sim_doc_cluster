"""Business logic services for the document similarity clustering system."""

import uuid
from datetime import datetime
from typing import List, Optional

from src.es_client import es_client
from src.models import (
    Article, ArticleCreate, ArticleTag, ArticleTopic, Cluster,
    ArticleResponse, SimilarArticlesResponse, ClusterResponse,
    RecheckResponse, HealthCheckResponse
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
    
    def submit_article(self, article_data: ArticleCreate) -> None:
        """Submit or update an article for similarity processing."""
        existing_article = self.es.get_article(article_data.article_id)
        now_iso = datetime.utcnow().isoformat()
        
        common_fields = {
            "title": article_data.title,
            "content": article_data.content,
            "publish_time": article_data.publish_time.isoformat(),
            "source": article_data.source,
            "state": article_data.state,
            "top": article_data.top,
            "tags": [tag.model_dump() for tag in article_data.tags],
            "topic": [topic.model_dump() for topic in article_data.topic],
            "tag_ids": [str(tag.id) for tag in article_data.tags],
            "topic_ids": [topic.id for topic in article_data.topic],
            "updated_at": now_iso
        }
        
        if existing_article:
            # Update mutable fields for idempotent submissions
            self.es.update_article(article_data.article_id, common_fields)
            return
        
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
            
            article_doc = {
                "article_id": article_data.article_id,
                **common_fields,
                "simhash": features["simhash"],
                "minhash_signature": features["minhash_signature"],
                "shingles": features["shingles"],
                "cluster_id": cluster_id,
                "cluster_status": "matched",
                "similarity_score": 1.0,
                "created_at": now_iso
            }
            
            self.es.index_article(article_doc)
            return
        
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
            **common_fields,
            "simhash": features["simhash"],
            "minhash_signature": features["minhash_signature"],
            "shingles": features["shingles"],
            "cluster_id": None,
            "cluster_status": "pending",
            "similarity_score": None,
            "created_at": now_iso
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
        self.redis.enqueue_similarity_job(job_data)
    
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
            state=article_data.get("state", 1),
            top=article_data.get("top", 0),
            tags=[ArticleTag(**tag) for tag in article_data.get("tags", [])],
            topic=[ArticleTopic(**topic) for topic in article_data.get("topic", [])],
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
                    state=article_data.get("state", 1),
                    top=article_data.get("top", 0),
                    tags=[ArticleTag(**tag) for tag in article_data.get("tags", [])],
                    topic=[ArticleTopic(**topic) for topic in article_data.get("topic", [])],
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
    
    def search_articles(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        sort: Optional[str] = None,
        state: Optional[int] = None,
        top: Optional[int] = None,
        title: Optional[str] = None,
        source: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        tag_id: Optional[str] = None,
        topic_ids: Optional[List[str]] = None
    ) -> List[str]:
        """Search articles by metadata filters."""
        return self.es.search_articles(
            page=page,
            page_size=page_size,
            sort=sort or "publish_time:desc",
            state=state,
            top=top,
            title=title,
            source=source,
            start_time=start_time,
            end_time=end_time,
            tag_id=tag_id,
            topic_ids=topic_ids or []
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
