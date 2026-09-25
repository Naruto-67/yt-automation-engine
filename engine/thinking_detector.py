# engine/thinking_detector.py — Dynamic Wire-Level AI Reasoning & Thinking Detector
"""
Zero-hardcoding Reasoning & Thinking Detector.
Inspects API responses at the wire/payload level across Google GenAI SDK,
OpenAI-compatible endpoints (Groq, DeepSeek R1, OpenRouter, GitHub Models),
and open-source reasoning tag formats to detect and measure internal Chain-of-Thought
without model name matching or static heuristics.
"""

import re
from typing import Dict, Any, Optional, List


class ThinkingDetector:
    """
    Dynamically identifies if an AI model engaged internal reasoning/thinking
    during response generation by inspecting wire-level response objects,
    dedicated payload attributes, token accounting metadata, and XML tag structures.
    """

    @staticmethod
    def detect_google_response(response: Any) -> Dict[str, Any]:
        """
        Inspects Google GenAI SDK response object (GenerateContentResponse)
        for native thought parts and candidates token metadata.
        """
        is_thinking = False
        method = "none"
        thought_tokens = 0
        thought_chars = 0
        thought_snippets: List[str] = []

        if response is None:
            return {
                "is_thinking": False,
                "method": "none",
                "thought_tokens": 0,
                "thought_chars": 0,
                "thought_snippet": ""
            }

        # 1. Native SDK candidate parts inspection (part.thought == True)
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                if getattr(part, "thought", False):
                    is_thinking = True
                    method = "native_part"
                    txt = getattr(part, "text", "") or ""
                    thought_chars += len(txt)
                    if txt.strip():
                        thought_snippets.append(txt.strip())

        # 2. Token usage metadata inspection
        usage = getattr(response, "usage_metadata", None)
        if usage:
            token_details = getattr(usage, "candidates_token_details", None)
            if token_details:
                t_tokens = getattr(token_details, "thinking_token_count", 0) or 0
                if t_tokens > 0:
                    is_thinking = True
                    thought_tokens = t_tokens
                    if method == "none":
                        method = "token_metadata"

        # 3. Text fallback for embedded tags
        raw_text = getattr(response, "text", "") or ""
        if not is_thinking and raw_text:
            tag_match = re.search(r"<(think|thought|THINKING)>([\s\S]*?)</\1>", raw_text, re.IGNORECASE)
            if tag_match:
                is_thinking = True
                method = "xml_tags"
                snip = tag_match.group(2).strip()
                thought_chars = len(snip)
                thought_snippets.append(snip)

        # Estimate tokens if not directly available from API metadata
        if thought_tokens == 0 and thought_chars > 0:
            thought_tokens = max(1, thought_chars // 4)

        full_snippet = " ".join(thought_snippets).replace("\n", " ").strip()
        if len(full_snippet) > 120:
            full_snippet = full_snippet[:120] + "..."

        return {
            "is_thinking": is_thinking,
            "method": method,
            "thought_tokens": thought_tokens,
            "thought_chars": thought_chars,
            "thought_snippet": full_snippet
        }

    @staticmethod
    def detect_openai_response(resp_json: Optional[Dict[str, Any]], raw_text: str = "") -> Dict[str, Any]:
        """
        Inspects OpenAI-compatible JSON responses (Groq, OpenRouter, DeepSeek R1, GitHub Models)
        for reasoning_content and completion_tokens_details.reasoning_tokens.
        """
        is_thinking = False
        method = "none"
        thought_tokens = 0
        thought_chars = 0
        thought_snippet = ""

        if not resp_json and not raw_text:
            return {
                "is_thinking": False,
                "method": "none",
                "thought_tokens": 0,
                "thought_chars": 0,
                "thought_snippet": ""
            }

        if resp_json and isinstance(resp_json, dict):
            # 1. Check choice message for reasoning_content (DeepSeek R1 / Groq reasoning models)
            choices = resp_json.get("choices", [])
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message", {})
                if isinstance(msg, dict):
                    reasoning_content = msg.get("reasoning_content") or msg.get("reasoning")
                    if reasoning_content and isinstance(reasoning_content, str) and reasoning_content.strip():
                        is_thinking = True
                        method = "reasoning_content"
                        thought_chars = len(reasoning_content.strip())
                        thought_snippet = reasoning_content.strip()

            # 2. Check token accounting in usage details
            usage = resp_json.get("usage", {})
            if isinstance(usage, dict):
                token_details = usage.get("completion_tokens_details", {})
                if isinstance(token_details, dict):
                    r_tokens = token_details.get("reasoning_tokens", 0) or 0
                    if r_tokens > 0:
                        is_thinking = True
                        thought_tokens = r_tokens
                        if method == "none":
                            method = "token_metadata"

        # 3. Check raw text for embedded tags (<think>...</think>)
        if not is_thinking and raw_text:
            tag_match = re.search(r"<(think|thought|THINKING)>([\s\S]*?)</\1>", raw_text, re.IGNORECASE)
            if tag_match:
                is_thinking = True
                method = "xml_tags"
                thought_snippet = tag_match.group(2).strip()
                thought_chars = len(thought_snippet)

        if thought_tokens == 0 and thought_chars > 0:
            thought_tokens = max(1, thought_chars // 4)

        clean_snippet = thought_snippet.replace("\n", " ").strip()
        if len(clean_snippet) > 120:
            clean_snippet = clean_snippet[:120] + "..."

        return {
            "is_thinking": is_thinking,
            "method": method,
            "thought_tokens": thought_tokens,
            "thought_chars": thought_chars,
            "thought_snippet": clean_snippet
        }
