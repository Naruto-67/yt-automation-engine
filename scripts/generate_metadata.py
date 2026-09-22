# scripts/generate_metadata.py — Ghost Engine V13.0
import json
import os
import yaml
from scripts.quota_manager import quota_manager
from engine.database import db
from engine.context import ctx
from engine.logger import logger

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f: return yaml.safe_load(f)

def _build_hashtags(niche: str) -> str:
    """Return a small set of hashtags appropriate for the niche, appended to description."""
    niche_lower = niche.lower()
    if any(k in niche_lower for k in ['storytelling', 'moral', 'pixar', 'anime', 'animation']):
        return "#shorts #animation #moralstory #storytime #pixar"
    elif any(k in niche_lower for k in ['fact', 'educational', 'education', 'science']):
        return "#shorts #facts #didyouknow #educational #learnontiktok"
    elif any(k in niche_lower for k in ['space', 'cosmic', 'stellar', 'galaxy']):
        return "#shorts #space #universe #spacefacts #astronomy"
    elif any(k in niche_lower for k in ['tech', 'ai', 'future', 'automation']):
        return "#shorts #tech #ai #futuretech #technology"
    elif any(k in niche_lower for k in ['horror', 'terror', 'scary', 'eldritch']):
        return "#shorts #horror #scary #creepy #darkfacts"
    else:
        return "#shorts #viral #fyp #trending"

def _build_fallback_title(niche: str) -> str:
    """
    Generate a curiosity-gap fallback title when the LLM SEO call fails.
    Avoids cliché openers ('Amazing', 'Incredible') that signal low-quality content.
    Rotates through archetype templates based on niche keywords.
    """
    import random
    niche_lower = niche.lower()

    if any(k in niche_lower for k in ['storytelling', 'moral', 'pixar', 'anime', 'animation', 'fictional']):
        templates = [
            "The Choice That Changed Everything 🎬 #shorts",
            "Nobody Expected This to Happen 🌟 #shorts",
            "One Decision. Zero Regrets. 🔥 #shorts",
            "The Secret He Carried for Years 💡 #shorts",
        ]
    elif any(k in niche_lower for k in ['space', 'cosmic', 'stellar', 'galaxy', 'universe']):
        templates = [
            "Scientists Can't Explain This Space Anomaly 🌌 #shorts",
            "The Object That Breaks All Physics Laws 🤯 #shorts",
            "This Star Shouldn't Exist — But It Does 🔭 #shorts",
            "The Void Scientists Refuse to Name 🌠 #shorts",
        ]
    elif any(k in niche_lower for k in ['horror', 'terror', 'scary', 'eldritch', 'dark']):
        templates = [
            "The Sound No Human Should Ever Hear 😱 #shorts",
            "This Creature Has No Natural Predators — Except One 🕷️ #shorts",
            "The Place Where Compasses Stop Working 🧭 #shorts",
            "Your Brain Does This While You Sleep 😰 #shorts",
        ]
    elif any(k in niche_lower for k in ['tech', 'ai', 'future', 'automation', 'technology']):
        templates = [
            "The Algorithm That Knows You Better Than You Do 🤖 #shorts",
            "This Tech Has Existed for 40 Years — Hidden 💻 #shorts",
            "Why Your Phone Lies to You Every Day 📱 #shorts",
            "The Code Running Silently in Every Device 🔐 #shorts",
        ]
    elif any(k in niche_lower for k in ['biology', 'science', 'body', 'nature', 'animal']):
        templates = [
            "Your Body Does This Every 7 Seconds — Silently 🧬 #shorts",
            "The Animal That Cannot Die of Old Age 🐙 #shorts",
            "This Plant Makes Its Own Light — No Sun Needed 🌿 #shorts",
            "The Organ Science Ignored for 300 Years 🫀 #shorts",
        ]
    else:
        templates = [
            "The Fact That Changes Everything You Thought 💡 #shorts",
            "Nobody Tells You This — But It's True 🔍 #shorts",
            "The Number That Breaks Human Intuition 🤯 #shorts",
            "This Happens Every Day — You Just Don't Notice 👁️ #shorts",
        ]

    return random.choice(templates)


def score_packaging_ctr(title: str, niche: str = "") -> dict:
    """
    CTR Packaging Scorer.

    Scores a YouTube Shorts title against 8 algorithmic curiosity archetypes
    that consistently produce above-average Click-Through Rates.

    Scoring breakdown (0-100):
    - Archetype match (+30): Matches one of the 8 proven viral patterns
    - Length compliance (+20): Under 60 chars before #shorts
    - No cliché opener (+15): Does not start with "Amazing/Incredible/Mind-blowing"
    - Has number or proper noun (+15): Concrete anchor (more credible than vague claims)
    - Has emoji (+10): 1-2 emojis signal visual energy
    - No generic question opener (+10): "Did you know" / "Have you ever" patterns penalized

    Returns:
        dict with keys: score (0-100), archetype, compliant_length, feedback
    """
    import re as _re
    score = 0
    feedback_parts = []

    # Strip #shorts for length check
    title_clean = _re.sub(r'#shorts?\s*', '', title, flags=_re.IGNORECASE).strip()

    # ── 8 Curiosity Archetype Patterns ────────────────────────────────────
    _ARCHETYPES = [
        (r'\b(zero|no|never|cannot|impossible|defies?|breaks?|without)\b', "Impossible Juxtaposition"),
        (r'\b(secret|hidden|nobody|never told|they don\'t|government|military)\b', "Forbidden Secret"),
        (r'\b(\d[\d,\.]*\s*(billion|million|trillion|years?|times?|percent|%)|every|entire|all of|outweigh|smallest|oldest|fastest|largest)\b', "Extreme Scale"),
        (r'\b(real(ly)? reason|why your|how your|secretly|silently|every (night|day|second|year))\b', "Hidden Mechanism"),
        (r'\b(kill|die|dead|never do|survive|danger|must not|lethal|fatal|kills? you|stay alive)\b', "Survival Instinct"),
        (r'\b(chose|sacrifice|abandon|despite|was right|lied to|saved \d+|by abandon)\b', "Moral Dilemma"),
        (r'\b(color|colour|frequency|no (word|name)|nameless|humans (can|cannot)|has no word)\b', "Forbidden Knowledge"),
        (r'\b(your body|you (are|were|have)|every human|nobody (knows|tells)|you never|we all)\b', "Identity Challenge"),
    ]

    archetype_matched = None
    title_lower = title_clean.lower()
    for pattern, name in _ARCHETYPES:
        if _re.search(pattern, title_lower):
            archetype_matched = name
            score += 30
            feedback_parts.append(f"✅ Archetype: {name}")
            break

    if not archetype_matched:
        feedback_parts.append("⚠️ No archetype match — title may feel generic")

    # ── Length compliance (<60 chars before #shorts) ──────────────────────
    char_count = len(title_clean)
    if char_count <= 60:
        score += 20
        feedback_parts.append(f"✅ Length: {char_count} chars (≤60)")
    elif char_count <= 70:
        score += 10
        feedback_parts.append(f"⚠️ Length: {char_count} chars (slightly over 60 target)")
    else:
        feedback_parts.append(f"❌ Length: {char_count} chars (over 70 — truncated by YouTube)")

    # ── No cliché opener ───────────────────────────────────────────────────
    _CLICHE_OPENERS = ["amazing", "incredible", "mind-blowing", "unbelievable", "shocking",
                       "you won't believe", "the most", "jaw-dropping", "epic", "insane"]
    has_cliche = any(title_lower.startswith(c) or f" {c}" in title_lower[:20] for c in _CLICHE_OPENERS)
    if not has_cliche:
        score += 15
        feedback_parts.append("✅ No cliché opener")
    else:
        feedback_parts.append("❌ Cliché opener detected — weakens CTR signal")

    # ── Contains number or proper noun ────────────────────────────────────
    has_number = bool(_re.search(r'\b\d+[\d,\.]*\b', title_clean))
    has_proper = bool(_re.search(r'\b[A-Z][a-z]{2,}\b', title_clean))
    if has_number or has_proper:
        score += 15
        feedback_parts.append(f"✅ Concrete anchor: {'number' if has_number else 'proper noun'}")
    else:
        feedback_parts.append("⚠️ No number or proper noun — abstract claims are less credible")

    # ── Has emoji ─────────────────────────────────────────────────────────
    emoji_count = len(_re.findall(r'[\U00010000-\U0010ffff]', title_clean, flags=_re.UNICODE))
    if 1 <= emoji_count <= 2:
        score += 10
        feedback_parts.append(f"✅ Emoji: {emoji_count} (optimal)")
    elif emoji_count == 0:
        feedback_parts.append("⚠️ No emoji — misses visual energy signal")
    else:
        feedback_parts.append(f"⚠️ Too many emojis ({emoji_count}) — looks spammy")

    # ── No generic question opener ─────────────────────────────────────────
    generic_q = ["did you know", "have you ever", "do you know", "what if i told you"]
    has_generic_q = any(title_lower.startswith(q) for q in generic_q)
    if not has_generic_q:
        score += 10
        feedback_parts.append("✅ No generic question opener")
    else:
        feedback_parts.append("❌ Generic question opener — algorithm-penalised pattern")

    score = min(100, max(0, score))
    grade = "🔴 Weak" if score < 40 else "🟡 Decent" if score < 65 else "🟢 Strong" if score < 85 else "⚡ Exceptional"

    return {
        "score": score,
        "grade": grade,
        "archetype": archetype_matched,
        "char_count": char_count,
        "compliant_length": char_count <= 60,
        "feedback": " | ".join(feedback_parts),
    }


def generate_seo_metadata(niche, script):
    print("🔍 [SEO] Generating optimized metadata...")

    channel_id = ctx.get_channel_id()
    intel = db.get_channel_intelligence(channel_id)
    prompts_cfg = load_config_prompts()
    
    tags_str = ", ".join(intel.get("recent_tags", [])) or niche
    vis_str = ", ".join(intel.get("preferred_visuals", [])) or "Cinematic"

    user_msg = prompts_cfg['seo_gen']['user_template'].format(script_text=script, recent_tags=tags_str, visual_preference=vis_str)

    hashtags = _build_hashtags(niche)

    try:
        raw_text, provider = quota_manager.generate_text(user_msg, task_type="seo", system_prompt=prompts_cfg['seo_gen']['system_prompt'])
        if raw_text:
            from engine.llm_router import UniversalGreedyJSONParser
            data = UniversalGreedyJSONParser.extract_json(raw_text)
            if not data or not isinstance(data, dict):
                start = raw_text.find('{')
                end = raw_text.rfind('}')
                if start != -1 and end != -1 and end > start:
                    data = json.loads(raw_text[start:end+1])
                else:
                    data = {}
                
                if "metadata" in data and isinstance(data["metadata"], dict):
                    data = data["metadata"]
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    data = data[0]
                    
                if not isinstance(data, dict):
                    data = {}
                
                safe_title_raw = data.get("title", _build_fallback_title(niche))
                if isinstance(safe_title_raw, list): 
                    safe_title_raw = safe_title_raw[0] if safe_title_raw else _build_fallback_title(niche)
                
                raw_title = str(safe_title_raw).replace("<", "").replace(">", "").strip()
                
                safe_title = raw_title[:85].rsplit(' ', 1)[0] if len(raw_title) > 85 else raw_title
                if "#shorts" not in safe_title.lower(): 
                    safe_title = f"{safe_title.strip()} #shorts"
                
                final_title = safe_title[:100] if len(safe_title) > 0 else _build_fallback_title(niche)

                # ── CTR Packaging Score ──────────────────────────────────
                try:
                    ctr_result = score_packaging_ctr(final_title, niche)
                    print(
                        f"   📦 [CTR SCORE] {ctr_result['grade']} {ctr_result['score']}/100 "
                        f"| Archetype: {ctr_result['archetype'] or 'None'} "
                        f"| {ctr_result['char_count']} chars "
                        f"| {ctr_result['feedback']}"
                    )
                except Exception as _ctr_err:
                    pass  # CTR scoring is advisory — never blocks metadata generation

                raw_tags = data.get("tags", ["shorts", niche])
                if isinstance(raw_tags, str):
                    safe_tags = [t.strip().replace("#", "") for t in raw_tags.split(",") if t.strip()]
                elif isinstance(raw_tags, list):
                    safe_tags = [str(t).strip().replace("#", "") for t in raw_tags if str(t).strip()]
                else:
                    safe_tags = ["shorts", niche]
                
                # Allow up to 500 chars of tags (YouTube limit) — old 400 cap was leaving value unused
                valid_tags = []
                total_len = 0
                for t in safe_tags:
                    if total_len + len(t) + 1 <= 490:
                        valid_tags.append(t)
                        total_len += len(t) + 1
                    else:
                        break
                
                # Extract high-converting pinned engagement comment
                raw_pinned = data.get("pinned_comment", "")
                pinned_comment = str(raw_pinned).replace("<", "").replace(">", "").strip() if raw_pinned else "What surprised you the most? Share below! 👇"

                # Monetization description CTA injection
                from engine.config_manager import config_manager
                settings = config_manager.get_settings()
                monetization = settings.get("monetization", {})
                is_monetization_enabled = monetization.get("enabled", True)
                cta_slot = monetization.get("description_cta", "") or monetization.get("cta_text", "")
                affiliate_link = monetization.get("affiliate_link", "") or monetization.get("cta_url", "")

                cta_text = ""
                if is_monetization_enabled and cta_slot:
                    cta_text = f"\n\n{cta_slot}"
                    if affiliate_link:
                        cta_text += f"\n🔗 {affiliate_link}"

                # Append hashtags to description — YouTube uses these for hashtag search surfacing
                raw_desc = str(data.get("description", "")).replace("<", "").replace(">", "").strip()
                if raw_desc:
                    full_desc = f"{raw_desc}{cta_text}\n\n{hashtags}"
                else:
                    full_desc = f"{cta_text}\n\n{hashtags}".strip() or hashtags

                return {
                    "title": final_title, 
                    "description": full_desc[:4900], 
                    "tags": valid_tags,
                    "pinned_comment": pinned_comment
                }, provider
    except Exception as e:
        # GOD-TIER FIX: Do not silently pass on extraction errors. Log them before falling back.
        logger.error(f"SEO Generation encountered an error: {e}. Executing fallback metadata.")
    
    # Fallback — use a niche-appropriate description and curiosity-gap title
    niche_lower = niche.lower()
    if any(k in niche_lower for k in ['storytelling', 'moral', 'pixar', 'anime', 'animation']):
        fallback_desc = f"Every short story hides a truth nobody tells you. Watch until the end. {hashtags}"
    elif any(k in niche_lower for k in ['space', 'cosmic', 'stellar', 'galaxy']):
        fallback_desc = f"The universe is stranger than any science fiction. Here's proof. {hashtags}"
    elif any(k in niche_lower for k in ['horror', 'dark', 'scary']):
        fallback_desc = f"Some facts are so unsettling they change how you see everything. {hashtags}"
    else:
        fallback_desc = f"The fact nobody teaches you — until now. {hashtags}"

    return {
        "title": _build_fallback_title(niche),
        "description": fallback_desc,
        "tags": ["shorts", niche, "viral", "facts", "fyp"],
        "pinned_comment": "What surprised you the most? Share below! 👇"
    }, "Fallback"
