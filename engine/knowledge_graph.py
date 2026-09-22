# engine/knowledge_graph.py — Ghost Engine V1.0
"""
Dynamic Knowledge Graph for Content Discovery and Coverage Balance.

Tracks covered topics, relationships (semantically_related, same_entity, contradicts),
content pillars, and unexplored adjacent spaces per channel.

Persistence:
    memory/knowledge_graph.json
"""

import os
import re
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from engine.logger import logger


_GRAPH_FILE = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "memory",
    "knowledge_graph.json"
)

_COMMON_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with",
    "about", "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "from", "up", "down", "of", "off", "over", "under", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "shall", "should", "may", "might", "must", "can", "could",
    "what", "why", "how", "when", "where", "who", "which", "this", "that", "these",
    "those", "there", "their", "they", "them", "his", "her", "its", "our", "your"
}


def _slugify(text: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
    words = [w for w in cleaned.split() if w]
    return "-".join(words[:10]) if words else "node"


def _extract_tags(text: str) -> List[str]:
    words = re.findall(r'[a-zA-Z0-9]{3,}', text.lower())
    return [w for w in words if w not in _COMMON_WORDS]


class KnowledgeGraph:
    """
    Directed semantic graph tracking YouTube Shorts content coverage.
    Stores nodes (topics) and edges (relations) per channel.
    """

    def __init__(self, file_path: str = _GRAPH_FILE):
        self.file_path = file_path
        self._ensure_storage()

    def _ensure_storage(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        if not os.path.exists(self.file_path):
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump({"channels": {}}, f, indent=2)
            except Exception as e:
                logger.error(f"[KNOWLEDGE_GRAPH] Init file error: {e}")

    def _load_data(self) -> Dict[str, Any]:
        if not os.path.exists(self.file_path):
            return {"channels": {}}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {"channels": {}}
                if "channels" not in data:
                    data["channels"] = {}
                return data
        except Exception as e:
            logger.debug(f"[KNOWLEDGE_GRAPH] Load error: {e}")
            return {"channels": {}}

    def _save_data(self, data: Dict[str, Any]):
        temp_file = f"{self.file_path}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.file_path)
        except Exception as e:
            logger.error(f"[KNOWLEDGE_GRAPH] Save error: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    def _get_channel_graph(self, data: Dict[str, Any], channel_id: str) -> Dict[str, Any]:
        chans = data.setdefault("channels", {})
        return chans.setdefault(channel_id, {
            "nodes": {},
            "edges": [],
            "pillars": {}
        })

    def add_covered(
        self,
        channel_id: str,
        topic: str,
        pillar: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> str:
        """
        Marks a topic as covered in the channel's knowledge graph.
        Creates semantic relation edges to existing nodes with tag overlap.
        """
        if not topic or not topic.strip():
            return ""

        node_id = _slugify(topic)
        tags = tags or _extract_tags(topic)
        pillar = (pillar or "general").strip().lower()

        data = self._load_data()
        ch_graph = self._get_channel_graph(data, channel_id)

        # Update or create node
        existing_node = ch_graph["nodes"].get(node_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        ch_graph["nodes"][node_id] = {
            "topic": topic.strip(),
            "status": "covered",
            "pillar": pillar,
            "tags": tags,
            "added_at": existing_node.get("added_at", now_iso) if existing_node else now_iso,
            "updated_at": now_iso
        }

        # Update pillar count
        pillars = ch_graph.setdefault("pillars", {})
        pillars[pillar] = pillars.get(pillar, 0) + 1

        # Automatically connect edges to related existing nodes
        existing_edges = {(e["source"], e["target"]): e for e in ch_graph.get("edges", [])}
        node_tags_set = set(tags)

        for other_id, other_node in ch_graph["nodes"].items():
            if other_id == node_id:
                continue
            other_tags = set(other_node.get("tags", []))
            common = node_tags_set & other_tags
            if common:
                overlap = len(common) / max(len(node_tags_set | other_tags), 1)
                if overlap >= 0.2:
                    rel = "same_entity" if overlap >= 0.5 else "semantically_related"
                    pair = (node_id, other_id)
                    rev_pair = (other_id, node_id)
                    if pair not in existing_edges and rev_pair not in existing_edges:
                        ch_graph["edges"].append({
                            "source": node_id,
                            "target": other_id,
                            "relation": rel,
                            "weight": round(overlap, 2),
                            "common_tags": list(common)
                        })

        self._save_data(data)
        logger.debug(f"[KNOWLEDGE_GRAPH] Added covered node '{node_id}' to {channel_id} (Pillar: {pillar})")
        return node_id

    def add_candidate(
        self,
        channel_id: str,
        topic: str,
        pillar: Optional[str] = None,
        tags: Optional[List[str]] = None,
        related_to_topic: Optional[str] = None,
        relation: str = "semantically_related"
    ) -> str:
        """
        Adds an unexplored topic candidate connected to an existing covered topic.
        """
        if not topic or not topic.strip():
            return ""

        node_id = _slugify(topic)
        tags = tags or _extract_tags(topic)
        pillar = (pillar or "general").strip().lower()

        data = self._load_data()
        ch_graph = self._get_channel_graph(data, channel_id)

        if node_id in ch_graph["nodes"] and ch_graph["nodes"][node_id].get("status") == "covered":
            return node_id  # Already covered

        now_iso = datetime.now(timezone.utc).isoformat()
        ch_graph["nodes"][node_id] = {
            "topic": topic.strip(),
            "status": "unexplored",
            "pillar": pillar,
            "tags": tags,
            "added_at": now_iso
        }

        if related_to_topic:
            src_id = _slugify(related_to_topic)
            if src_id in ch_graph["nodes"]:
                ch_graph["edges"].append({
                    "source": src_id,
                    "target": node_id,
                    "relation": relation,
                    "weight": 0.8
                })

        self._save_data(data)
        return node_id

    def is_topic_covered(self, channel_id: str, topic: str, similarity_threshold: float = 0.65) -> bool:
        """
        Checks whether a topic (or one virtually identical) is already covered.
        """
        data = self._load_data()
        ch_graph = self._get_channel_graph(data, channel_id)
        target_slug = _slugify(topic)

        # Check exact slug
        if target_slug in ch_graph["nodes"] and ch_graph["nodes"][target_slug].get("status") == "covered":
            return True

        # Check token Jaccard similarity against all covered nodes
        target_tags = set(_extract_tags(topic))
        if not target_tags:
            return False

        for n_id, n_data in ch_graph["nodes"].items():
            if n_data.get("status") == "covered":
                n_tags = set(n_data.get("tags", []))
                if not n_tags:
                    continue
                overlap = len(target_tags & n_tags) / len(target_tags | n_tags)
                if overlap >= similarity_threshold:
                    return True

        return False

    def find_adjacent_unexplored(
        self,
        channel_id: str,
        topic: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Finds unexplored candidate topics connected to covered topics.
        """
        data = self._load_data()
        ch_graph = self._get_channel_graph(data, channel_id)

        candidates = []
        if topic:
            src_id = _slugify(topic)
            for edge in ch_graph.get("edges", []):
                other_id = None
                if edge.get("source") == src_id:
                    other_id = edge.get("target")
                elif edge.get("target") == src_id:
                    other_id = edge.get("source")

                if other_id and other_id in ch_graph["nodes"]:
                    node = ch_graph["nodes"][other_id]
                    if node.get("status") == "unexplored":
                        candidates.append({
                            "id": other_id,
                            "topic": node.get("topic"),
                            "pillar": node.get("pillar"),
                            "relation": edge.get("relation"),
                            "weight": edge.get("weight", 0.5)
                        })
        else:
            for n_id, node in ch_graph["nodes"].items():
                if node.get("status") == "unexplored":
                    candidates.append({
                        "id": n_id,
                        "topic": node.get("topic"),
                        "pillar": node.get("pillar"),
                        "relation": "general_candidate",
                        "weight": 0.5
                    })

        candidates.sort(key=lambda x: x.get("weight", 0.0), reverse=True)
        return candidates[:top_k]

    def get_coverage_map(self, channel_id: str) -> Dict[str, Any]:
        """
        Analyzes topic coverage distribution across content pillars.
        Identifies over-explored and under-explored pillars to balance production.
        """
        data = self._load_data()
        ch_graph = self._get_channel_graph(data, channel_id)

        nodes = ch_graph.get("nodes", {})
        covered_nodes = [n for n in nodes.values() if n.get("status") == "covered"]
        total_covered = len(covered_nodes)

        pillar_counts: Dict[str, int] = {}
        for n in covered_nodes:
            p = n.get("pillar", "general")
            pillar_counts[p] = pillar_counts.get(p, 0) + 1

        under_explored = []
        over_explored = []

        if pillar_counts and total_covered > 4:
            avg_count = total_covered / len(pillar_counts)
            for p, count in pillar_counts.items():
                if count < max(1, avg_count * 0.5):
                    under_explored.append(p)
                elif count > avg_count * 1.8:
                    over_explored.append(p)

        recent_covered = sorted(
            covered_nodes,
            key=lambda x: x.get("added_at", ""),
            reverse=True
        )[:10]

        return {
            "channel_id": channel_id,
            "total_covered": total_covered,
            "pillar_counts": pillar_counts,
            "under_explored_pillars": under_explored,
            "over_explored_pillars": over_explored,
            "recent_topics": [r.get("topic") for r in recent_covered]
        }


# Global singleton
knowledge_graph = KnowledgeGraph()
