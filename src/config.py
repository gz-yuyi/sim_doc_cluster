"""Configuration management for the document similarity clustering system."""

import os
from typing import List, Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field

# Load environment variables from .env file
load_dotenv()


class Settings(BaseSettings):
    """Application settings."""
    
    # Application Settings
    app_name: str = Field(default="sim-doc-cluster", env="APP_NAME")
    app_version: str = Field(default="0.1.0", env="APP_VERSION")
    debug: bool = Field(default=False, env="DEBUG")
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")
    
    # Elasticsearch Configuration
    es_host: str = Field(default="localhost", env="ES_HOST")
    es_port: int = Field(default=9200, env="ES_PORT")
    es_username: Optional[str] = Field(default=None, env="ES_USERNAME")
    es_password: Optional[str] = Field(default=None, env="ES_PASSWORD")
    es_index_prefix: str = Field(default="sim_doc", env="ES_INDEX_PREFIX")
    es_articles_index: str = Field(default="articles", env="ES_ARTICLES_INDEX")
    es_clusters_index: str = Field(default="clusters", env="ES_CLUSTERS_INDEX")
    
    # Redis Configuration
    redis_host: str = Field(default="localhost", env="REDIS_HOST")
    redis_port: int = Field(default=6379, env="REDIS_PORT")
    redis_db: int = Field(default=0, env="REDIS_DB")
    redis_password: Optional[str] = Field(default=None, env="REDIS_PASSWORD")
    redis_queue_name: str = Field(default="similarity_jobs", env="REDIS_QUEUE_NAME")
    
    # Similarity Algorithm Settings
    simhash_bit_size: int = Field(default=64, env="SIMHASH_BIT_SIZE")
    minhash_permutations: int = Field(default=128, env="MINHASH_PERMUTATIONS")
    minhash_bands: int = Field(default=20, env="MINHASH_BANDS")
    minhash_rows_per_band: int = Field(default=6, env="MINHASH_ROWS_PER_BAND")
    shingle_size: int = Field(default=5, env="SHINGLE_SIZE")
    similarity_threshold: float = Field(default=0.8, env="SIMILARITY_THRESHOLD")
    
    # API Settings
    api_v1_prefix: str = Field(default="/api/v1", env="API_V1_PREFIX")
    cors_origins: List[str] = Field(default=["*"], env="CORS_ORIGINS")
    
    @property
    def es_url(self) -> str:
        """Get the full Elasticsearch URL."""
        if self.es_username and self.es_password:
            return f"http://{self.es_username}:{self.es_password}@{self.es_host}:{self.es_port}"
        return f"http://{self.es_host}:{self.es_port}"
    
    @property
    def es_articles_index_full(self) -> str:
        """Get the full articles index name."""
        return f"{self.es_index_prefix}_{self.es_articles_index}"
    
    @property
    def es_clusters_index_full(self) -> str:
        """Get the full clusters index name."""
        return f"{self.es_index_prefix}_{self.es_clusters_index}"
    
    @property
    def redis_url(self) -> str:
        """Get the full Redis URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


# Global settings instance
settings = Settings()