"""Elasticsearch client and index management for the document similarity clustering system."""

import json
from datetime import datetime
from typing import Dict, List, Optional, Any

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError

from src.config import settings


class ElasticsearchClient:
    """Elasticsearch client with index management."""
    
    def __init__(self):
        """Initialize Elasticsearch client."""
        self.client = Elasticsearch(
            hosts=[settings.es_url],
            verify_certs=False,
            ssl_show_warn=False
        )
        self.articles_index = settings.es_articles_index_full
        self.clusters_index = settings.es_clusters_index_full
    
    def ping(self) -> bool:
        """Check if Elasticsearch is available."""
        return self.client.ping()
    
    def create_indices(self) -> None:
        """Create indices with proper mappings if they don't exist."""
        # Create articles index
        if not self.client.indices.exists(index=self.articles_index):
            articles_mapping = {
                "mappings": {
                    "properties": {
                        "article_id": {"type": "keyword"},
                        "title": {"type": "text", "analyzer": "ik_max_word"},
                        "content": {"type": "text", "analyzer": "ik_max_word"},
                        "publish_time": {"type": "date"},
                        "source": {"type": "keyword"},
                        "state": {"type": "integer"},
                        "top": {"type": "integer"},
                        "tags": {
                            "type": "object",
                            "properties": {
                                # Tag IDs can be large (e.g. 64-bit IDs), so store as long
                                "id": {"type": "long"},
                                "name": {"type": "keyword"}
                            }
                        },
                        "topic": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "keyword"},
                                "name": {"type": "keyword"}
                            }
                        },
                        "tag_ids": {"type": "keyword"},
                        "topic_ids": {"type": "keyword"},
                        "simhash": {"type": "keyword"},
                        "minhash_signature": {"type": "keyword"},
                        "cluster_id": {"type": "keyword"},
                        "cluster_status": {"type": "keyword"},
                        "similarity_score": {"type": "float"},
                        "created_at": {"type": "date"},
                        "updated_at": {"type": "date"}
                    }
                },
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "analysis": {
                        "analyzer": {
                            "ik_max_word": {
                                "type": "ik_max_word"
                            }
                        }
                    }
                }
            }
            self.client.indices.create(index=self.articles_index, body=articles_mapping)
        
        # Create clusters index
        if not self.client.indices.exists(index=self.clusters_index):
            clusters_mapping = {
                "mappings": {
                    "properties": {
                        "cluster_id": {"type": "keyword"},
                        "article_ids": {"type": "keyword"},
                        "size": {"type": "integer"},
                        "representative_article_id": {"type": "keyword"},
                        "top_terms": {"type": "object", "enabled": False},
                        "last_updated": {"type": "date"},
                        "created_at": {"type": "date"}
                    }
                },
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0
                }
            }
            self.client.indices.create(index=self.clusters_index, body=clusters_mapping)

    def clear_all_documents(self) -> None:
        """Delete all documents by recreating indices."""
        for index in [self.articles_index, self.clusters_index]:
            if self.client.indices.exists(index=index):
                self.client.indices.delete(index=index, ignore=[404])
        self.create_indices()
    
    def index_article(self, article_data: Dict[str, Any]) -> str:
        """Index an article document."""
        try:
            response = self.client.index(
                index=self.articles_index,
                id=article_data["article_id"],
                body=article_data,
                refresh="wait_for"
            )
        except NotFoundError:
            # Lazily initialize indices if they haven't been created yet
            self.create_indices()
            response = self.client.index(
                index=self.articles_index,
                id=article_data["article_id"],
                body=article_data,
                refresh="wait_for"
            )
        return response["_id"]
    
    def get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get an article by ID."""
        try:
            response = self.client.get(index=self.articles_index, id=article_id)
            return response["_source"]
        except NotFoundError:
            return None
    
    def update_article(self, article_id: str, updates: Dict[str, Any]) -> bool:
        """Update an article."""
        try:
            self.client.update(
                index=self.articles_index,
                id=article_id,
                body={"doc": updates},
                refresh="wait_for"
            )
            return True
        except NotFoundError:
            return False
    
    def index_cluster(self, cluster_data: Dict[str, Any]) -> str:
        """Index a cluster document."""
        try:
            response = self.client.index(
                index=self.clusters_index,
                id=cluster_data["cluster_id"],
                body=cluster_data,
                refresh="wait_for"
            )
        except NotFoundError:
            self.create_indices()
            response = self.client.index(
                index=self.clusters_index,
                id=cluster_data["cluster_id"],
                body=cluster_data,
                refresh="wait_for"
            )
        return response["_id"]
    
    def get_cluster(self, cluster_id: str) -> Optional[Dict[str, Any]]:
        """Get a cluster by ID."""
        try:
            response = self.client.get(index=self.clusters_index, id=cluster_id)
            return response["_source"]
        except NotFoundError:
            return None
    
    def update_cluster(self, cluster_id: str, updates: Dict[str, Any]) -> bool:
        """Update a cluster."""
        try:
            self.client.update(
                index=self.clusters_index,
                id=cluster_id,
                body={"doc": updates},
                refresh="wait_for"
            )
            return True
        except NotFoundError:
            return False
    
    def search_simhash(self, simhash: str) -> List[Dict[str, Any]]:
        """Search for articles with exact simhash match."""
        query = {
            "query": {
                "term": {
                    "simhash": simhash
                }
            },
            "size": 1
        }
        
        response = self.client.search(index=self.articles_index, body=query)
        return [hit["_source"] for hit in response["hits"]["hits"]]
    
    def search_minhash_candidates(self, minhash_signature: List[str], size: int = 50) -> List[Dict[str, Any]]:
        """Search for candidate articles using MinHash LSH."""
        # Take first 20 bands for LSH (adjust based on configuration)
        bands_to_search = minhash_signature[:20]
        
        query = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"minhash_signature": band}} for band in bands_to_search
                    ],
                    "minimum_should_match": 1
                }
            },
            "size": size
        }
        
        response = self.client.search(index=self.articles_index, body=query)
        return [hit["_source"] for hit in response["hits"]["hits"]]
    
    def search_articles_by_cluster(self, cluster_id: str, size: int = 100) -> List[Dict[str, Any]]:
        """Search for articles in a specific cluster."""
        query = {
            "query": {
                "term": {
                    "cluster_id": cluster_id
                }
            },
            "size": size,
            "sort": [
                {"publish_time": {"order": "desc"}}
            ]
        }
        
        response = self.client.search(index=self.articles_index, body=query)
        return [hit["_source"] for hit in response["hits"]["hits"]]
    
    def search_articles(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        sort: str = "publish_time:desc",
        state: Optional[int] = None,
        top: Optional[int] = None,
        title: Optional[str] = None,
        source: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        tag_id: Optional[str] = None,
        topic_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Search articles by metadata filters and include total count."""
        from_ = (page - 1) * page_size
        valid_sort_fields = {"publish_time", "created_at", "updated_at"}
        
        if ":" not in sort:
            raise ValueError("Sort parameter must be in format 'field:order'")
        
        sort_field, sort_order = sort.split(":")
        if sort_field not in valid_sort_fields or sort_order not in {"asc", "desc"}:
            raise ValueError(f"Invalid sort parameter. Valid fields: {sorted(valid_sort_fields)}, orders: ['asc', 'desc']")
        
        bool_query: Dict[str, Any] = {"filter": []}
        must_queries: List[Dict[str, Any]] = []
        
        if state is not None:
            bool_query["filter"].append({"term": {"state": state}})
        if top is not None:
            bool_query["filter"].append({"term": {"top": top}})
        if source:
            bool_query["filter"].append({"term": {"source": source}})
        if tag_id:
            bool_query["filter"].append({"term": {"tag_ids": tag_id}})
        if topic_ids:
            bool_query["filter"].append({"terms": {"topic_ids": topic_ids}})
        if start_time or end_time:
            range_filter: Dict[str, Any] = {}
            if start_time:
                range_filter["gte"] = start_time
            if end_time:
                range_filter["lte"] = end_time
            bool_query["filter"].append({"range": {"publish_time": range_filter}})
        if title:
            must_queries.append({
                "match": {
                    "title": {
                        "query": title,
                        "operator": "and"
                    }
                }
            })
        
        query_body: Dict[str, Any] = {
            "query": {
                "bool": bool_query
            },
            "from": from_,
            "size": page_size,
            "sort": [{sort_field: {"order": sort_order}}]
        }
        
        if must_queries:
            query_body["query"]["bool"]["must"] = must_queries
        
        response = self.client.search(index=self.articles_index, body=query_body)
        hits = [hit["_source"] for hit in response["hits"]["hits"]]
        total_field = response["hits"].get("total")
        if isinstance(total_field, dict):
            total = total_field.get("value", len(hits))
        else:
            total = total_field or len(hits)

        return {
            "items": hits,
            "total": int(total)
        }
    
    def get_cluster_stats(self) -> Dict[str, Any]:
        """Get cluster statistics."""
        # Count total articles
        articles_response = self.client.count(index=self.articles_index)
        total_articles = articles_response["count"]
        
        # Count total clusters
        clusters_response = self.client.count(index=self.clusters_index)
        total_clusters = clusters_response["count"]
        
        # Get cluster size distribution
        size_distribution_query = {
            "size": 0,
            "aggs": {
                "size_distribution": {
                    "terms": {
                        "field": "size",
                        "size": 20
                    }
                }
            }
        }
        
        size_response = self.client.search(index=self.clusters_index, body=size_distribution_query)
        size_buckets = size_response["aggregations"]["size_distribution"]["buckets"]
        
        return {
            "total_articles": total_articles,
            "total_clusters": total_clusters,
            "size_distribution": size_buckets
        }


# Global Elasticsearch client instance
es_client = ElasticsearchClient()
