"""Text similarity algorithms for document clustering."""

import hashlib
import struct
from typing import List, Set, Tuple, Dict, Any

import mmh3
from datasketch import MinHash
from simhash import Simhash

from src.config import settings


class TextFeatureExtractor:
    """Extract text features for similarity calculation."""
    
    def __init__(self):
        """Initialize with configuration settings."""
        self.simhash_bit_size = settings.simhash_bit_size
        self.minhash_permutations = settings.minhash_permutations
        self.minhash_bands = settings.minhash_bands
        self.minhash_rows_per_band = settings.minhash_rows_per_band
        self.shingle_size = settings.shingle_size
        self.similarity_threshold = settings.similarity_threshold
    
    def extract_features(self, text: str) -> Dict[str, Any]:
        """Extract all features from text."""
        return {
            "simhash": self.compute_simhash(text),
            "minhash_signature": self.compute_minhash_signature(text),
            "shingles": self.generate_shingles(text)
        }
    
    def compute_simhash(self, text: str) -> str:
        """Compute SimHash fingerprint for text."""
        # Clean and normalize text
        text = text.strip().lower()
        
        # Create features (words)
        features = text.split()
        
        # Compute SimHash
        simhash = Simhash(features, f=self.simhash_bit_size)
        
        # Return as hexadecimal string
        return format(simhash.value, f'0{self.simhash_bit_size//4}x')
    
    def compute_minhash_signature(self, text: str) -> List[str]:
        """Compute MinHash signature for LSH."""
        # Generate shingles first
        shingles = self.generate_shingles(text)
        
        # Create MinHash object
        minhash = MinHash(num_perm=self.minhash_permutations)
        
        # Add shingles to MinHash
        for shingle in shingles:
            minhash.update(shingle.encode('utf-8'))
        
        # Convert to list of hash values
        hash_values = minhash.digest()
        
        # Convert to bands for LSH
        bands = []
        for i in range(self.minhash_bands):
            start = i * self.minhash_rows_per_band
            end = start + self.minhash_rows_per_band
            band_values = hash_values[start:end]
            
            # Create band signature by hashing the band values
            band_str = ','.join(map(str, band_values))
            band_hash = hashlib.md5(band_str.encode('utf-8')).hexdigest()[:8]
            bands.append(band_hash)
        
        return bands
    
    def generate_shingles(self, text: str) -> List[str]:
        """Generate character-based shingles from text."""
        # Clean and normalize text
        text = text.strip().lower()
        
        # Generate k-gram shingles
        shingles = []
        for i in range(len(text) - self.shingle_size + 1):
            shingle = text[i:i + self.shingle_size]
            shingles.append(shingle)
        
        return shingles
    
    def jaccard_similarity(self, shingles_a: List[str], shingles_b: List[str]) -> float:
        """Calculate Jaccard similarity between two sets of shingles."""
        set_a = set(shingles_a)
        set_b = set(shingles_b)
        
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        
        if union == 0:
            return 0.0
        
        return intersection / union
    
    def simhash_similarity(self, simhash_a: str, simhash_b: str) -> int:
        """Calculate Hamming distance between two SimHash values."""
        # Convert hex strings to integers
        hash_a = int(simhash_a, 16)
        hash_b = int(simhash_b, 16)
        
        # Calculate Hamming distance
        xor_result = hash_a ^ hash_b
        hamming_distance = bin(xor_result).count('1')
        
        return hamming_distance
    
    def is_simhash_duplicate(self, simhash_a: str, simhash_b: str, threshold: int = 3) -> bool:
        """Check if two SimHash values are duplicates based on Hamming distance threshold."""
        distance = self.simhash_similarity(simhash_a, simhash_b)
        return distance <= threshold
    
    def find_similar_candidates(self, shingles_a: List[str], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find candidates that meet the similarity threshold."""
        similar_candidates = []
        
        for candidate in candidates:
            candidate_shingles = candidate.get("shingles", [])
            if not candidate_shingles:
                continue
            
            similarity = self.jaccard_similarity(shingles_a, candidate_shingles)
            
            if similarity >= self.similarity_threshold:
                candidate_copy = candidate.copy()
                candidate_copy["similarity_score"] = similarity
                similar_candidates.append(candidate_copy)
        
        # Sort by similarity score (descending)
        similar_candidates.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        return similar_candidates
    
    def merge_clusters(self, cluster_ids: Set[str]) -> str:
        """Merge multiple clusters into a single cluster ID."""
        if not cluster_ids:
            return None
        
        if len(cluster_ids) == 1:
            return cluster_ids.pop()
        
        # For now, use the smallest cluster ID as the merged cluster ID
        # In a production system, you might want more sophisticated logic
        return min(cluster_ids)
    
    def generate_cluster_id(self, article_id: str) -> str:
        """Generate a cluster ID for a new article."""
        return f"cluster_{article_id}"


class SimilarityCalculator:
    """High-level similarity calculation interface."""
    
    def __init__(self):
        """Initialize with feature extractor."""
        self.extractor = TextFeatureExtractor()
    
    def calculate_article_similarity(self, article_text: str, candidate_articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate similarity between an article and candidate articles."""
        # Extract features from the article
        features = self.extractor.extract_features(article_text)
        
        # Check for exact duplicates using SimHash
        exact_duplicates = []
        for candidate in candidate_articles:
            candidate_simhash = candidate.get("simhash")
            if candidate_simhash and self.extractor.is_simhash_duplicate(
                features["simhash"], candidate_simhash
            ):
                exact_duplicates.append(candidate)
        
        if exact_duplicates:
            return {
                "status": "duplicate",
                "similarity_score": 1.0,
                "similar_articles": exact_duplicates,
                "features": features
            }
        
        # Find similar articles using Jaccard similarity
        similar_articles = self.extractor.find_similar_candidates(
            features["shingles"], candidate_articles
        )
        
        if similar_articles:
            return {
                "status": "similar",
                "similarity_score": similar_articles[0]["similarity_score"],
                "similar_articles": similar_articles,
                "features": features
            }
        
        return {
            "status": "unique",
            "similarity_score": 0.0,
            "similar_articles": [],
            "features": features
        }
    
    def should_create_new_cluster(self, similar_articles: List[Dict[str, Any]]) -> bool:
        """Determine if a new cluster should be created."""
        return len(similar_articles) == 0
    
    def find_best_cluster(self, similar_articles: List[Dict[str, Any]]) -> str:
        """Find the best cluster to join from similar articles."""
        if not similar_articles:
            return None
        
        # Group by cluster_id
        cluster_scores = {}
        for article in similar_articles:
            cluster_id = article.get("cluster_id")
            if cluster_id:
                if cluster_id not in cluster_scores:
                    cluster_scores[cluster_id] = []
                cluster_scores[cluster_id].append(article["similarity_score"])
        
        if not cluster_scores:
            return None
        
        # Find cluster with highest average similarity
        best_cluster = None
        best_score = 0.0
        
        for cluster_id, scores in cluster_scores.items():
            avg_score = sum(scores) / len(scores)
            if avg_score > best_score:
                best_score = avg_score
                best_cluster = cluster_id
        
        return best_cluster


# Global similarity calculator instance
similarity_calculator = SimilarityCalculator()