"""Utility functions for the document similarity clustering system."""

import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import HTTPException, status


def generate_trace_id() -> str:
    """Generate a unique trace ID for request tracking."""
    return str(uuid.uuid4())


def get_current_timestamp() -> datetime:
    """Get current UTC timestamp."""
    return datetime.utcnow()


def format_timestamp(timestamp: datetime) -> str:
    """Format timestamp to ISO 8601 string."""
    return timestamp.isoformat() + "Z"


def create_error_response(error_code: str, message: str, trace_id: str) -> Dict[str, Any]:
    """Create a standardized error response."""
    return {
        "error": {
            "code": error_code,
            "message": message
        },
        "trace_id": trace_id
    }


def raise_http_exception(status_code: int, error_code: str, message: str, trace_id: str):
    """Raise an HTTP exception with standardized error format."""
    raise HTTPException(
        status_code=status_code,
        detail=create_error_response(error_code, message, trace_id)
    )


def validate_article_id(article_id: str) -> bool:
    """Validate article ID format."""
    if not article_id or not isinstance(article_id, str):
        return False
    
    # Basic validation: non-empty string
    return len(article_id.strip()) > 0


def validate_cluster_id(cluster_id: str) -> bool:
    """Validate cluster ID format."""
    if not cluster_id or not isinstance(cluster_id, str):
        return False
    
    # Basic validation: should start with "cluster_"
    return cluster_id.startswith("cluster_") and len(cluster_id) > len("cluster_")


def sanitize_text(text: str, max_length: int = 200000) -> str:
    """Sanitize text content."""
    if not text:
        return ""
    
    # Remove excessive whitespace
    text = " ".join(text.split())
    
    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length]
    
    return text


def extract_top_terms(text: str, max_terms: int = 10) -> list:
    """Extract top terms from text for cluster representation."""
    if not text:
        return []
    
    # Simple word frequency analysis
    words = text.lower().split()
    word_freq = {}
    
    for word in words:
        if len(word) > 1:  # Skip single characters
            word_freq[word] = word_freq.get(word, 0) + 1
    
    # Sort by frequency and take top terms
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    top_words = sorted_words[:max_terms]
    
    # Calculate weights (normalized frequencies)
    total_freq = sum(freq for _, freq in top_words)
    if total_freq == 0:
        total_freq = 1
    
    top_terms = []
    for word, freq in top_words:
        weight = freq / total_freq
        top_terms.append({"term": word, "weight": round(weight, 3)})
    
    return top_terms


def calculate_eta(queue_length: int, avg_processing_time_ms: int = 100) -> int:
    """Calculate estimated processing time based on queue length."""
    if queue_length <= 0:
        return 0
    
    # Add some buffer time
    return queue_length * avg_processing_time_ms + 50


def merge_cluster_data(existing_cluster: Dict[str, Any], new_article_id: str) -> Dict[str, Any]:
    """Merge new article into existing cluster data."""
    updated_cluster = existing_cluster.copy()
    
    # Add new article to the list
    if "article_ids" not in updated_cluster:
        updated_cluster["article_ids"] = []
    
    if new_article_id not in updated_cluster["article_ids"]:
        updated_cluster["article_ids"].append(new_article_id)
    
    # Update size
    updated_cluster["size"] = len(updated_cluster["article_ids"])
    
    # Update timestamp
    updated_cluster["last_updated"] = get_current_timestamp().isoformat()
    
    return updated_cluster


def create_new_cluster(article_id: str, article_title: str, article_content: str) -> Dict[str, Any]:
    """Create a new cluster with the given article."""
    cluster_id = f"cluster_{article_id}"
    
    # Extract top terms from article
    full_text = f"{article_title} {article_content}"
    top_terms = extract_top_terms(full_text)
    
    return {
        "cluster_id": cluster_id,
        "article_ids": [article_id],
        "size": 1,
        "representative_article_id": article_id,
        "top_terms": top_terms,
        "last_updated": get_current_timestamp().isoformat(),
        "created_at": get_current_timestamp().isoformat()
    }


def paginate_results(items: list, page: int, page_size: int) -> Dict[str, Any]:
    """Paginate a list of results."""
    total = len(items)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    
    paginated_items = items[start_idx:end_idx]
    
    return {
        "items": paginated_items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    }


def validate_date_range(start_date: Optional[datetime], end_date: Optional[datetime]) -> bool:
    """Validate date range."""
    if start_date and end_date:
        return start_date <= end_date
    return True


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes == 0:
        return "0B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f}{size_names[i]}"


def is_valid_language_code(language: str) -> bool:
    """Validate language code format."""
    if not language or not isinstance(language, str):
        return False
    
    # Basic validation for common language codes (e.g., "zh-CN", "en-US")
    parts = language.split("-")
    if len(parts) == 1:
        # Simple language code (e.g., "en")
        return len(parts[0]) == 2 and parts[0].isalpha()
    elif len(parts) == 2:
        # Language with region (e.g., "zh-CN")
        return (len(parts[0]) == 2 and parts[0].isalpha() and 
                len(parts[1]) == 2 and parts[1].isalpha())
    
    return False


def normalize_source(source: str) -> str:
    """Normalize source string."""
    if not source:
        return "unknown"
    
    # Remove whitespace and convert to lowercase
    normalized = source.strip().lower()
    
    # Replace common separators with underscore
    for sep in [" ", "-", ".", "_"]:
        normalized = normalized.replace(sep, "_")
    
    # Remove multiple consecutive underscores
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    
    return normalized