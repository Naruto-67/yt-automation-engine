# engine/episodic_memory.py — Ghost Engine V1.0
"""
Episodic Memory Engine with Swappable Similarity Backend (TF-IDF Default).

Maintains an append-only JSONL log of produced videos per channel, recording
topics, hooks, script summaries, quality/critic scores, and performance feedback.
Allows querying semantically similar past topics without consuming any LLM quota.

Key Components:
1. SimilarityBackend: Abstract interface for semantic text comparison.
2. TfidfSimilarityBackend: Pure-Python TF-IDF + cosine similarity (zero external dependencies).
3. EpisodicMemory: High-level store managing logs, similarity search, and performance tagging.
"""

import os
import re
import json
import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from engine.logger import logger


_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "could", "did", "do", "does", "doing", "down",
    "during", "each", "few", "for", "from", "further", "had", "has", "have", "having",
    "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i",
    "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most",
    "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only",
    "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same", "she",
    "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those", "through", "to",
    "too", "under", "until", "up", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "whom", "why", "with", "would", "you", "your",
    "yours", "yourself", "yourselves"
}


class SimilarityBackend(ABC):
    """Abstract interface for text similarity calculation."""

    @abstractmethod
    def compute_similarity(self, query: str, documents: List[str]) -> List[float]:
        """Returns a list of float similarity scores (0.0 to 1.0) for each document."""
        pass


class TfidfSimilarityBackend(SimilarityBackend):
    """
    Pure Python TF-IDF with Cosine Similarity.
    Zero external dependencies, zero API quota usage.
    """

    def _tokenize(self, text: str) -> List[str]:
        words = re.findall(r'[a-zA-Z0-9]+', text.lower())
        return [w for w in words if len(w) > 2 and w not in _STOPWORDS]

    def compute_similarity(self, query: str, documents: List[str]) -> List[float]:
        if not documents:
            return []

        all_docs = [query] + documents
        tokenized_docs = [self._tokenize(d) for d in all_docs]

        # Vocabulary
        vocab = sorted(list(set(w for doc in tokenized_docs for w in doc)))
        if not vocab:
            return [0.0] * len(documents)

        v_indices = {w: i for i, w in enumerate(vocab)}
        n_docs = len(all_docs)

        # Document Frequency (DF)
        df = [0] * len(vocab)
        for doc in tokenized_docs:
            for w in set(doc):
                df[v_indices[w]] += 1

        # Inverse Document Frequency (IDF)
        idf = [math.log(1.0 + (n_docs / (1.0 + count))) for count in df]

        # Compute TF-IDF vectors
        vectors = []
        for doc in tokenized_docs:
            vec = [0.0] * len(vocab)
            if doc:
                tf_counts = {}
                for w in doc:
                    tf_counts[w] = tf_counts.get(w, 0) + 1
                doc_len = len(doc)
                for w, cnt in tf_counts.items():
                    idx = v_indices[w]
                    vec[idx] = (cnt / doc_len) * idf[idx]
            vectors.append(vec)

        query_vec = vectors[0]
        doc_vectors = vectors[1:]

        # Cosine similarity between query_vec and each doc_vec
        q_norm = math.sqrt(sum(x * x for x in query_vec))
        if q_norm == 0.0:
            return [0.0] * len(documents)

        similarities = []
        for d_vec in doc_vectors:
            d_norm = math.sqrt(sum(x * x for x in d_vec))
            if d_norm == 0.0:
                similarities.append(0.0)
            else:
                dot = sum(q * d for q, d in zip(query_vec, d_vec))
                similarities.append(round(dot / (q_norm * d_norm), 4))

        return similarities


class EpisodicMemory:
    """
    Episodic memory store for tracking video productions and retrospective learning.
    Stores records in memory/episodic_memory.jsonl.
    """

    def __init__(self, backend: Optional[SimilarityBackend] = None):
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.memory_dir = os.path.join(root_dir, "memory")
        os.makedirs(self.memory_dir, exist_ok=True)
        self.log_file = os.path.join(self.memory_dir, "episodic_memory.jsonl")
        self.backend = backend or TfidfSimilarityBackend()

    def _read_all(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.log_file):
            return []
        records = []
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"[EPISODIC MEMORY] Error reading log file: {e}")
        return records

    def log_video(
        self,
        channel_id: str,
        topic: str,
        hook: str,
        script_summary: str,
        quality_score: float = 7.0,
        critic_scores: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Record a newly drafted/produced video into episodic memory.
        """
        entry = {
            "id": f"{channel_id}_{int(datetime.now(timezone.utc).timestamp())}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channel_id": channel_id,
            "topic": topic,
            "hook": hook,
            "script_summary": script_summary[:300],
            "quality_score": quality_score,
            "critic_scores": critic_scores or {},
            "performance_tier": "unrated",
            "views": 0,
            "retention": 0.0,
            "metadata": metadata or {},
        }

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.debug(f"[EPISODIC MEMORY] Logged video entry for '{topic[:40]}...' (Channel: {channel_id})")
        except Exception as e:
            logger.error(f"[EPISODIC MEMORY] Failed to write entry: {e}")

        return entry

    def query_similar(
        self,
        channel_id: str,
        topic: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find past similar videos for the specified channel using the similarity backend.
        """
        records = [r for r in self._read_all() if r.get("channel_id") == channel_id]
        if not records:
            return []

        doc_texts = [f"{r.get('topic', '')} {r.get('hook', '')}" for r in records]
        similarities = self.backend.compute_similarity(topic, doc_texts)

        scored = []
        for rec, sim in zip(records, similarities):
            if sim > 0.05:  # filter noise
                item = rec.copy()
                item["similarity_score"] = sim
                scored.append(item)

        scored.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored[:top_k]

    def tag_performance(
        self,
        topic_or_id: str,
        views: int,
        retention: float = 0.0
    ) -> bool:
        """
        Tag a past video with actual YouTube view count and retention percentage.
        Updates performance_tier: breakout | high | average | low.
        """
        records = self._read_all()
        updated = False

        # Classify tier
        if views >= 10000 or retention >= 75.0:
            tier = "breakout"
        elif views >= 2000 or retention >= 60.0:
            tier = "high"
        elif views >= 500 or retention >= 45.0:
            tier = "average"
        else:
            tier = "low"

        for r in records:
            if r.get("id") == topic_or_id or r.get("topic") == topic_or_id:
                r["views"] = views
                r["retention"] = retention
                r["performance_tier"] = tier
                r["updated_at"] = datetime.now(timezone.utc).isoformat()
                updated = True
                break

        if updated:
            try:
                with open(self.log_file, "w", encoding="utf-8") as f:
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                logger.debug(f"[EPISODIC MEMORY] Tagged '{topic_or_id}' with {views} views -> Tier: {tier}")
                return True
            except Exception as e:
                logger.error(f"[EPISODIC MEMORY] Failed to update performance tag: {e}")

        return False


# Singleton instance
episodic_memory = EpisodicMemory()

