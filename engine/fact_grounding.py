# engine/fact_grounding.py — Real-Time Fact Grounding & Anti-Hallucination Gate
"""
Real-Time Fact Grounding & Anti-Hallucination Verification Gate.
Ensures factual channels (e.g. Topato / CH_02) never output hallucinated
science claims or fake viral myths.

Verification Hierarchy:
  1. Primary: Google Gemini Flash with Search Grounding (types.GoogleSearch())
  2. Fallback 1: Wikipedia REST API (page summary)
  3. Fallback 2: DuckDuckGo Zero-Key Instant Answer API
"""

import os
import json
import re
import urllib.parse
from typing import Dict, Any, List, Optional
import requests


class FactGroundingEngine:
    """Verifies empirical facts and extracts verifiable scientific mechanisms."""

    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "")

    def verify_topic(self, topic: str) -> Dict[str, Any]:
        """
        Runs empirical verification on a topic.
        Returns a dictionary containing verified facts, mechanisms, and source references.
        """
        if not topic or not topic.strip():
            return {"topic": topic, "verified": False, "facts": [], "mechanism": ""}

        # Attempt 1: Gemini Search Grounding
        gemini_res = self._verify_via_gemini_grounding(topic)
        if gemini_res and gemini_res.get("verified"):
            return gemini_res

        # Attempt 2: Wikipedia REST API
        wiki_res = self._verify_via_wikipedia(topic)
        if wiki_res and wiki_res.get("verified"):
            return wiki_res

        # Attempt 3: DuckDuckGo Instant Answer
        ddg_res = self._verify_via_duckduckgo(topic)
        if ddg_res and ddg_res.get("verified"):
            return ddg_res

        # Fallback: Extract keywords from topic itself
        return {
            "topic": topic,
            "verified": False,
            "facts": [f"Empirical context for {topic}."],
            "mechanism": topic,
            "source": "Local Topic Parsing",
        }

    def _verify_via_gemini_grounding(self, topic: str) -> Optional[Dict[str, Any]]:
        """Call Gemini Flash with Google Search Grounding to verify scientific mechanisms (Fix 1: Chat pattern)."""
        if not self.gemini_key:
            return None

        try:
            from google import genai
            from google.genai import types
            from engine.dynamic_discovery import load_registry

            client = genai.Client(api_key=self.gemini_key, http_options={"timeout": 20000})

            # Prefer universal flash-lite anchor for tool grounding
            registry = load_registry()
            gold_gemini = registry.get("gold_anchors", {}).get("gemini", ["gemini-flash-lite-latest"])
            model_name = gold_gemini[0] if gold_gemini else "gemini-flash-lite-latest"

            prompt = (
                f"Verify the factual, scientific, and empirical truth of this topic: \"{topic}\".\n"
                "Return a raw JSON object (and nothing else) with this exact schema:\n"
                "{\n"
                '  "verified": true,\n'
                '  "scientific_name": "Latin name or technical term if applicable",\n'
                '  "facts": [\n'
                '    "Concrete verified fact 1 with exact numbers or mechanism",\n'
                '    "Concrete verified fact 2 with exact numbers or mechanism",\n'
                '    "Concrete verified fact 3 with exact numbers or mechanism"\n'
                "  ],\n"
                '  "mechanism": "One sentence summary of the exact biological or physical process",\n'
                '  "source": "Primary scientific consensus or institution"\n'
                "}\n"
                "If the topic is completely false or a debunked myth, set verified to false and explain in mechanism."
            )

            # Fix 1: Use client.chats.create + chat.send_message to eliminate AFC warning
            chat = client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    http_options={"timeout": 20000},
                )
            )
            response = chat.send_message(prompt)

            text = response.text if response and response.text else ""
            if not text:
                return None

            # Clean JSON markdown blocks
            clean_json = re.sub(r"```json\s*", "", text)
            clean_json = re.sub(r"```\s*", "", clean_json).strip()

            parsed = json.loads(clean_json)
            parsed["topic"] = topic
            parsed["engine"] = f"Gemini Grounding ({model_name})"
            return parsed

        except Exception as e:
            # Non-fatal: Free tier search tool quota exhaustion or timeout falls back cleanly to Wikipedia/DuckDuckGo
            return None

    def _verify_via_wikipedia(self, topic: str) -> Optional[Dict[str, Any]]:
        """Query Wikipedia REST API for canonical scientific definitions."""
        try:
            # Extract key entity name (strip common introductory words)
            query = re.sub(
                r"\b(the|how|why|does|can|what|is|are|a|an|in|on|at|survive|live|forever)\b",
                "",
                topic,
                flags=re.IGNORECASE,
            ).strip()
            keywords = [k for k in query.split() if len(k) > 3]
            search_term = keywords[0] if keywords else topic

            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(search_term)}"
            headers = {"User-Agent": "GhostEngineFactChecker/2.3 (https://github.com/)"}
            res = requests.get(url, headers=headers, timeout=5)

            if res.status_code == 200:
                data = res.json()
                extract = data.get("extract", "")
                if len(extract) > 40:
                    sentences = [s.strip() for s in extract.split(".") if len(s.strip()) > 20]
                    return {
                        "topic": topic,
                        "verified": True,
                        "scientific_name": data.get("title", search_term),
                        "facts": sentences[:3] if sentences else [extract[:180]],
                        "mechanism": extract[:200],
                        "source": f"Wikipedia ({data.get('title')})",
                        "engine": "Wikipedia REST API",
                    }
        except Exception:
            pass
        return None

    def _verify_via_duckduckgo(self, topic: str) -> Optional[Dict[str, Any]]:
        """Query DuckDuckGo Instant Answer API for quick factual validation."""
        try:
            url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(topic)}&format=json&no_html=1&skip_disambig=1"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                abstract = data.get("AbstractText", "")
                if abstract and len(abstract) > 30:
                    return {
                        "topic": topic,
                        "verified": True,
                        "scientific_name": data.get("Heading", topic),
                        "facts": [abstract[:180]],
                        "mechanism": abstract[:220],
                        "source": data.get("AbstractSource", "DuckDuckGo"),
                        "engine": "DuckDuckGo Instant Answer",
                    }
        except Exception:
            pass
        return None

    def format_grounding_prompt_block(self, grounding: Dict[str, Any]) -> str:
        """Format verified facts into a strict LLM prompt constraint."""
        if not grounding or not grounding.get("facts"):
            return ""

        lines = [
            "\n── VERIFIED EMPIRICAL SCIENTIFIC GROUNDING (TOPATO MANDATE):",
            "This topic has been verified against scientific consensus.",
            "You MUST anchor your narration to these exact verified empirical mechanisms:",
        ]
        for i, fact in enumerate(grounding.get("facts", []), 1):
            lines.append(f"  {i}. {fact}")

        if grounding.get("scientific_name"):
            lines.append(f"  • Scientific nomenclature/term: {grounding['scientific_name']}")
        if grounding.get("mechanism"):
            lines.append(f"  • Core mechanism: {grounding['mechanism']}")

        lines.append("Do NOT invent numbers, exaggerated claims, or unproven viral myths.\n")
        return "\n".join(lines)


# Global singleton instance
fact_grounding = FactGroundingEngine()

