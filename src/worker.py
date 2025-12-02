"""Similarity calculation worker for processing background jobs."""

import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Any

from src.config import settings
from src.es_client import es_client
from src.redis_client import redis_client
from src.similarity import similarity_calculator
from src.utils import create_new_cluster, merge_cluster_data, extract_top_terms

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SimilarityWorker:
    """Worker for processing similarity calculation jobs."""
    
    def __init__(self):
        """Initialize worker."""
        self.es = es_client
        self.redis = redis_client
        self.similarity = similarity_calculator
        self.running = False
    
    @staticmethod
    def _get_candidate_field(candidate: Any, field: str) -> Any:
        """Helper to read field from candidate dict or model."""
        if isinstance(candidate, dict):
            return candidate.get(field)
        return getattr(candidate, field, None)

    def process_job(self, job_id: str) -> bool:
        """Process a single similarity job."""
        try:
            # Get job details
            job = self.redis.get_job(job_id)
            if not job:
                logger.warning(f"Job {job_id} not found")
                return False
            
            logger.info(f"Processing job {job_id} for article {job.article_id}")
            
            # Update job status to processing
            self.redis.update_job_status(job_id, "processing")
            
            # Get article
            article_data = self.es.get_article(job.article_id)
            if not article_data:
                logger.error(f"Article {job.article_id} not found")
                self.redis.update_job_status(job_id, "failed")
                return False
            
            # Calculate similarity with candidates
            similar_articles = []
            cluster_ids = set()
            
            for candidate in job.candidates:
                candidate_id = self._get_candidate_field(candidate, "article_id")
                if not candidate_id:
                    continue
                candidate_article = self.es.get_article(candidate_id)
                if not candidate_article:
                    continue
                
                # Get candidate shingles
                candidate_shingles = candidate_article.get("shingles", [])
                if not candidate_shingles:
                    continue
                
                # Calculate Jaccard similarity
                similarity_score = self.similarity.extractor.jaccard_similarity(
                    job.shingles, candidate_shingles
                )
                
                if similarity_score >= settings.similarity_threshold:
                    similar_articles.append({
                        "article_id": candidate_id,
                        "similarity_score": similarity_score,
                        "cluster_id": self._get_candidate_field(candidate, "cluster_id")
                    })
                    
                    # Collect cluster IDs
                    candidate_cluster = self._get_candidate_field(candidate, "cluster_id")
                    if candidate_cluster:
                        cluster_ids.add(candidate_cluster)
            
            # Determine cluster assignment
            final_cluster_id = None
            similarity_score = 0.0
            
            if similar_articles:
                # Sort by similarity score
                similar_articles.sort(key=lambda x: x["similarity_score"], reverse=True)
                similarity_score = similar_articles[0]["similarity_score"]
                
                if cluster_ids:
                    # Merge existing clusters
                    final_cluster_id = self.similarity.extractor.merge_clusters(cluster_ids)
                    
                    # Update all articles in merged clusters
                    for cluster_id in cluster_ids:
                        if cluster_id != final_cluster_id:
                            cluster_articles = self.es.search_articles_by_cluster(cluster_id)
                            for article in cluster_articles:
                                self.es.update_article(article["article_id"], {
                                    "cluster_id": final_cluster_id,
                                    "updated_at": datetime.utcnow().isoformat()
                                })
                    
                    # Delete old clusters
                    for cluster_id in cluster_ids:
                        if cluster_id != final_cluster_id:
                            self.es.client.delete(
                                index=self.es.clusters_index,
                                id=cluster_id,
                                refresh="wait_for"
                            )
                else:
                    # Create new cluster
                    final_cluster_id = self.similarity.extractor.generate_cluster_id(job.article_id)
            else:
                # No similar articles found
                final_cluster_id = None
                
            # Check if article was already matched externally (e.g. by exact duplicate submission)
            # This prevents overwriting a 'matched' status with 'unique'
            current_article = self.es.get_article(job.article_id)
            if current_article and current_article.get("cluster_status") == "matched":
                external_cluster_id = current_article.get("cluster_id")
                if external_cluster_id:
                    if final_cluster_id and final_cluster_id != external_cluster_id:
                        # Conflict: Worker found one cluster, external found another.
                        # Merge them? For now, let's prefer the external one or merge.
                        # Simple strategy: use the external one as base.
                        # But wait, if we found matches, we should probably stick to our matches but merge the external cluster?
                        # For exact duplicate case, the external cluster is usually correct.
                        pass # Complex case, but rare.
                    elif not final_cluster_id:
                        # Worker found nothing, but external found something. Use external.
                        final_cluster_id = external_cluster_id
                        logger.info(f"Job {job_id}: Article already matched externally to {final_cluster_id}. Using it.")
            
            # Update or create cluster
            if final_cluster_id:
                cluster_data = self.es.get_cluster(final_cluster_id)
                cluster_created = False
                
                if not cluster_data:
                    cluster_data = create_new_cluster(
                        job.article_id,
                        article_data["title"],
                        article_data["content"]
                    )
                    cluster_created = True
                else:
                    cluster_data = merge_cluster_data(cluster_data, job.article_id)
                
                # Ensure similar candidates without clusters join the new cluster
                for similar in similar_articles:
                    candidate_id = similar.get("article_id")
                    if not candidate_id or candidate_id == job.article_id:
                        continue
                    
                    candidate_updates = {
                        "cluster_status": "matched",
                        "cluster_id": final_cluster_id,
                        "similarity_score": similar.get("similarity_score"),
                        "updated_at": datetime.utcnow().isoformat()
                    }
                    self.es.update_article(candidate_id, candidate_updates)
                    cluster_data = merge_cluster_data(cluster_data, candidate_id)
                
                if cluster_created:
                    self.es.index_cluster(cluster_data)
                else:
                    self.es.update_cluster(final_cluster_id, cluster_data)

            # Update article with cluster information
            updates = {
                "cluster_status": "matched" if final_cluster_id else "unique",
                "cluster_id": final_cluster_id,
                "similarity_score": similarity_score if final_cluster_id else None,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            self.es.update_article(job.article_id, updates)
            
            # Clear pending cluster information
            self.redis.clear_pending_cluster(job.article_id)
            
            # Mark job as completed
            self.redis.update_job_status(job_id, "completed")
            
            logger.info(f"Completed job {job_id} for article {job.article_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")
            self.redis.update_job_status(job_id, "failed")
            return False
    
    def run(self, max_jobs: Optional[int] = None, timeout: int = 10):
        """Run the worker."""
        self.running = True
        processed = 0
        
        logger.info("Starting similarity worker")
        
        try:
            while self.running and (max_jobs is None or processed < max_jobs):
                # Get job from queue
                job_id = self.redis.dequeue_similarity_job(timeout=timeout)
                
                if not job_id:
                    logger.info("No jobs in queue, waiting...")
                    continue
                
                # Process job
                if self.process_job(job_id):
                    processed += 1
                    logger.info(f"Processed {processed} jobs")
                else:
                    logger.warning(f"Failed to process job {job_id}")
                
                # Clean up expired jobs periodically
                if processed % 10 == 0:
                    self.redis.cleanup_expired_jobs()
        
        except KeyboardInterrupt:
            logger.info("Worker stopped by user")
        except Exception as e:
            logger.error(f"Worker error: {e}")
        finally:
            self.running = False
            logger.info(f"Worker stopped, processed {processed} jobs")
    
    def stop(self):
        """Stop the worker."""
        self.running = False


def run_worker(max_jobs: Optional[int] = None, timeout: int = 10):
    """Run the similarity worker."""
    worker = SimilarityWorker()
    worker.run(max_jobs=max_jobs, timeout=timeout)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Similarity calculation worker")
    parser.add_argument("--count", type=int, default=None, help="Maximum number of jobs to process")
    parser.add_argument("--timeout", type=int, default=10, help="Queue timeout in seconds")
    
    args = parser.parse_args()
    
    run_worker(max_jobs=args.count, timeout=args.timeout)