"""Similarity calculation worker for processing background jobs."""

import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Set

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
                candidate_article = self.es.get_article(candidate["article_id"])
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
                        "article_id": candidate["article_id"],
                        "similarity_score": similarity_score,
                        "cluster_id": candidate.get("cluster_id")
                    })
                    
                    # Collect cluster IDs
                    if candidate.get("cluster_id"):
                        cluster_ids.add(candidate["cluster_id"])
            
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
            
            # Update article with cluster information
            updates = {
                "cluster_status": "matched" if final_cluster_id else "unique",
                "cluster_id": final_cluster_id,
                "similarity_score": similarity_score if final_cluster_id else None,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            self.es.update_article(job.article_id, updates)
            
            # Update or create cluster
            if final_cluster_id:
                cluster_data = self.es.get_cluster(final_cluster_id)
                
                if cluster_data:
                    # Update existing cluster
                    updated_cluster = merge_cluster_data(cluster_data, job.article_id)
                    self.es.update_cluster(final_cluster_id, updated_cluster)
                else:
                    # Create new cluster
                    new_cluster = create_new_cluster(
                        job.article_id,
                        article_data["title"],
                        article_data["content"]
                    )
                    self.es.index_cluster(new_cluster)
            
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