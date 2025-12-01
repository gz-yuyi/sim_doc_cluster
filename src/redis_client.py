"""Redis client and queue management for the document similarity clustering system."""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

import redis
from redis.exceptions import ConnectionError, RedisError

from src.config import settings
from src.models import SimilarityJob


class RedisClient:
    """Redis client with queue management."""
    
    def __init__(self):
        """Initialize Redis client."""
        self.client = redis.from_url(settings.redis_url, decode_responses=True)
        self.queue_name = settings.redis_queue_name
        self.pending_prefix = "cluster_pending:"
        self.job_prefix = "similarity_job:"
    
    def ping(self) -> bool:
        """Check if Redis is available."""
        try:
            return self.client.ping()
        except ConnectionError:
            return False
    
    def enqueue_similarity_job(self, job_data: Dict[str, Any]) -> str:
        """Enqueue a similarity calculation job."""
        job_id = f"job_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        
        job = SimilarityJob(
            job_id=job_id,
            article_id=job_data["article_id"],
            shingles=job_data["shingles"],
            candidates=job_data["candidates"],
            created_at=datetime.utcnow(),
            status="pending"
        )
        
        # Store job details
        self.client.setex(
            f"{self.job_prefix}{job_id}",
            3600,  # Expire after 1 hour
            json.dumps(job.dict(), default=str)
        )
        
        # Add to queue
        self.client.lpush(self.queue_name, job_id)
        
        return job_id
    
    def dequeue_similarity_job(self, timeout: int = 10) -> Optional[str]:
        """Dequeue a similarity calculation job."""
        result = self.client.brpop(self.queue_name, timeout=timeout)
        if result:
            _, job_id = result
            return job_id
        return None
    
    def get_job(self, job_id: str) -> Optional[SimilarityJob]:
        """Get job details by ID."""
        job_data = self.client.get(f"{self.job_prefix}{job_id}")
        if job_data:
            try:
                data = json.loads(job_data)
                return SimilarityJob(**data)
            except (json.JSONDecodeError, TypeError):
                return None
        return None
    
    def update_job_status(self, job_id: str, status: str) -> bool:
        """Update job status."""
        job_data = self.client.get(f"{self.job_prefix}{job_id}")
        if job_data:
            try:
                data = json.loads(job_data)
                data["status"] = status
                data["updated_at"] = datetime.utcnow().isoformat()
                
                self.client.setex(
                    f"{self.job_prefix}{job_id}",
                    3600,
                    json.dumps(data, default=str)
                )
                return True
            except (json.JSONDecodeError, TypeError):
                return False
        return False
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        result = self.client.delete(f"{self.job_prefix}{job_id}")
        return result > 0
    
    def set_pending_cluster(self, article_id: str, cluster_id: Optional[str], eta_ms: int = 120) -> None:
        """Set pending cluster information for an article."""
        data = {
            "cluster_id": cluster_id,
            "eta_ms": eta_ms,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.client.setex(
            f"{self.pending_prefix}{article_id}",
            300,  # Expire after 5 minutes
            json.dumps(data)
        )
    
    def get_pending_cluster(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get pending cluster information for an article."""
        data = self.client.get(f"{self.pending_prefix}{article_id}")
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None
    
    def clear_pending_cluster(self, article_id: str) -> bool:
        """Clear pending cluster information for an article."""
        result = self.client.delete(f"{self.pending_prefix}{article_id}")
        return result > 0
    
    def get_queue_length(self) -> int:
        """Get the current queue length."""
        return self.client.llen(self.queue_name)
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        queue_length = self.get_queue_length()
        
        # Count pending jobs
        pending_count = 0
        for key in self.client.scan_iter(f"{self.job_prefix}*"):
            job_data = self.client.get(key)
            if job_data:
                try:
                    data = json.loads(job_data)
                    if data.get("status") == "pending":
                        pending_count += 1
                except json.JSONDecodeError:
                    pass
        
        return {
            "queue_length": queue_length,
            "pending_jobs": pending_count,
            "processing_jobs": pending_count - queue_length
        }
    
    def cleanup_expired_jobs(self) -> int:
        """Clean up expired jobs."""
        deleted_count = 0
        for key in self.client.scan_iter(f"{self.job_prefix}*"):
            if not self.client.exists(key):
                deleted_count += 1
        return deleted_count
    
    def health_check(self) -> Dict[str, str]:
        """Perform health check on Redis."""
        try:
            # Test basic connectivity
            if not self.ping():
                return {"redis": "fail", "message": "Cannot connect to Redis"}
            
            # Test basic operations
            test_key = "health_check_test"
            self.client.set(test_key, "test", ex=10)
            value = self.client.get(test_key)
            self.client.delete(test_key)
            
            if value != "test":
                return {"redis": "fail", "message": "Redis read/write test failed"}
            
            # Check queue operations
            queue_length = self.get_queue_length()
            
            return {
                "redis": "pass",
                "message": f"Redis is healthy, queue length: {queue_length}"
            }
        except RedisError as e:
            return {"redis": "fail", "message": f"Redis error: {str(e)}"}

    def clear_all_tasks(self) -> Dict[str, int]:
        """Clear all queued jobs, job metadata and pending markers."""
        queue_deleted = self.client.delete(self.queue_name)
        
        job_deleted = 0
        for key in self.client.scan_iter(f"{self.job_prefix}*"):
            job_deleted += int(self.client.delete(key))
        
        pending_deleted = 0
        for key in self.client.scan_iter(f"{self.pending_prefix}*"):
            pending_deleted += int(self.client.delete(key))
        
        return {
            "queue_deleted": queue_deleted,
            "jobs_deleted": job_deleted,
            "pending_deleted": pending_deleted,
        }


# Global Redis client instance
redis_client = RedisClient()