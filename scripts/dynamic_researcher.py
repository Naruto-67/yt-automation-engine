# scripts/dynamic_researcher.py
import re
import json
import yaml
import os
import random
import traceback
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import set_channel_context, notify_research_complete, notify_summary
from engine.database import db
from engine.models import VideoJob, ChannelConfig
from engine.logger import logger

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)

def _jaccard_similarity(a: str, b: str) -> float:
    ta = set(re.findall(r'[a-z0-9]{2,}', a.lower()))
    tb = set(re.findall(r'[a-z0-9]{2,}', b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def get_deep_channel_context(youtube) -> str:
    if not youtube:
        return "No channel data."
    try:
        uploads_id = youtube.channels().list(
            part="contentDetails", mine=True
        ).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)

        vids = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=20
        ).execute()
        quota_manager.consume_points("youtube", 1)

        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids:
            return "Brand new channel — generate broad content."

        stats = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        quota_manager.consume_points("youtube", 1)

        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()

        video_data = sorted([
            {
                "title":        i["snippet"]["title"],
                "views":        int(i["statistics"].get("viewCount", 0)),
                "published_at": i["snippet"].get("publishedAt", ""),
            }
            for i in stats.get("items", []) if i["snippet"].get("publishedAt", "") > cutoff
        ], key=lambda x: x["views"], reverse=True)

        if not video_data:
            video_data = sorted([
                {"title": i["snippet"]["title"], "views": int(i["statistics"].get("viewCount", 0))}
                for i in stats.get("items", [])
            ], key=lambda x: x["views"], reverse=True)[:3]

        return "📊 Top Recent Content (last 30 days):\n" + "\n".join([
            f"- '{v['title']}' | {v['views']:,} views" for v in video_data[:5]
        ])
    except Exception as e:
        trace = traceback.format_exc()
        logger.error(f"Channel context fetch failed:\n{trace}")
        return "Generate broad niches."

def research_competitors(youtube, niche: str, top_n: int = 3) -> str:
    if not youtube:
        return ""

    settings = {}
    try:
        from engine.config_manager import config_manager
        settings = config_manager.get_settings()
    except Exception:
        pass

    top_n    = settings.get("intelligence", {}).get("competitor_channels_to_analyze", 3)
    top_vids = settings.get("intelligence", {}).get("competitor_top_videos", 5)

    try:
        search = youtube.search().list(
            part="snippet", type="channel", q=niche,
            order="relevance", maxResults=top_n
        ).execute()
        quota_manager.consume_points("youtube", 100)

        competitor_ids = [item["snippet"]["channelId"] for item in search.get("items", []) if "channelId" in item["snippet"]]
        if not competitor_ids:
            return ""

        insights = []
        all_competitor_titles = []

        for ch_id in competitor_ids[:top_n]:
            try:
                ch_res = youtube.channels().list(part="contentDetails,snippet", id=ch_id).execute()
                quota_manager.consume_points("youtube", 1)

                if not ch_res.get("items"):
                    continue

                ch_name    = ch_res["items"][0]["snippet"]["title"]
                uploads_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

                pl_items = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=top_vids).execute()
                quota_manager.consume_points("youtube", 1)

                vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in pl_items.get("items", [])]
                if not vid_ids:
                    continue

                vids = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
                quota_manager.consume_points("youtube", 1)

                top_titles = sorted([
                    {
                        "title":    v["snippet"]["title"],
                        "views":    int(v["statistics"].get("viewCount", 0)),
                        "tags":     v["snippet"].get("tags", [])[:5],
                    }
                    for v in vids.get("items", [])
                ], key=lambda x: x["views"], reverse=True)[:3]

                if top_titles:
                    all_competitor_titles.extend([t["title"] for t in top_titles])
                    insights.append(
                        f"Channel: {ch_name}\n" + "\n".join([f"  - '{t['title']}' | {t['views']:,} views" for t in top_titles])
                    )
            except Exception:
                continue

        result = "\n\n".join(insights)

        # ── GAP ANALYSIS: surface what competitors are NOT covering ──────────
        # Pass the competitor titles back so the researcher prompt can ask the
        # LLM to find underserved angles. This is appended as a separate section.
        if all_competitor_titles:
            titles_block = "\n".join([f"  - {t}" for t in all_competitor_titles[:15]])
            result += (
                f"\n\n🕳️ COMPETITOR CONTENT GAPS — these are topics competitors ARE covering.\n"
                f"When generating topics, look for angles these videos MISSED, sub-topics they\n"
                f"glossed over, or counterarguments to their most-viewed content:\n"
                f"{titles_block}"
            )

        return result
    except Exception as e:
        logger.error(f"Competitor research failed: {e}")
        return ""

def _generate_topics_and_evolve_niche(channel_config: ChannelConfig, needed: int, channel_context: str, competitor_context: str, historical_topics: list, prompts_cfg: dict, active_niche: str) -> tuple:
    intel = db.get_channel_intelligence(channel_config.channel_id)
    competitor_section = f"\n\n🏆 COMPETITOR INSIGHTS:\n{competitor_context}" if competitor_context else ""

    # ── BUG FIX: Anchor topic generation to the CONFIGURED niche ──────────────
    # The research prompt used to be built from `active_niche` which came from
    # `intel.get("evolved_niche")`. Once the evolved_niche drifted (e.g. to
    # "cosmic abyss dossiers"), every subsequent research run compounded the
    # drift — the only topics generated were more cosmic/abyss/light content.
    #
    # Fix:
    #   • `prompt_niche` — the niche string fed to the LLM. For FACTUAL channels
    #     this is ALWAYS the configured niche from channels.yaml, so the researcher
    #     produces varied educational/random fun facts.
    #   • The evolved_niche (if any) is passed as *additional context* so the
    #     LLM can still use learnings, but it cannot hijack the anchor.
    #   • For FICTIONAL channels (which benefit from creative evolution), the
    #     evolved_niche remains the primary anchor as before.
    is_factual = getattr(channel_config, "content_type", None) == "factual"

    if is_factual:
        prompt_niche = active_niche
        evolved      = intel.get("evolved_niche")
        if evolved and evolved != active_niche and evolved != channel_config.niche:
            print(f"📌 [RESEARCH] Factual channel — anchoring to configured sub-niche: '{active_niche}'")
            print(f"   (Evolved niche '{evolved[:80]}…' ignored.)")
    else:
        prompt_niche = active_niche

    # ── Pillar performance context ────────────────────────────────────────────
    # title_templates field repurposed as pillar_performance storage (JSON dict).
    # Format: {"psychology": {"videos": 5, "total_views": 48000}, ...}
    # Tells the researcher to make more videos in pillars that are winning.
    pillar_context = ""
    pillar_data    = intel.get("title_templates", [])  # repurposed field
    if isinstance(pillar_data, dict) and pillar_data:
        sorted_pillars = sorted(
            pillar_data.items(),
            key=lambda x: (x[1].get("total_views", 0) / max(x[1].get("videos", 1), 1)),
            reverse=True
        )
        top    = [p for p, _ in sorted_pillars[:3]]
        bottom = [p for p, _ in sorted_pillars[-2:]] if len(sorted_pillars) > 3 else []
        pillar_context = (
            f"📊 PILLAR PERFORMANCE DATA (from your channel's actual videos):\n"
            f"  Top performing pillars (prioritise these): {', '.join(top)}\n"
        )
        if bottom:
            pillar_context += f"  Underperforming pillars (use sparingly): {', '.join(bottom)}\n"
        print(f"🏛️  [RESEARCH] Prioritising pillars: {', '.join(top)}")

    # ── Growth phase context ──────────────────────────────────────────────────
    # Detects the channel's current growth stage from sub count and adjusts
    # topic strategy: launch → variety, growth → double down on winners,
    # monetization → high-RPM education topics.
    phase_context  = ""
    phase_data     = intel.get("rule_timestamps", {})
    sub_count      = phase_data.get("__sub_count__", 0)
    if sub_count < 500:
        growth_phase = "launch"
        phase_context = (
            "🚀 GROWTH PHASE: LAUNCH (< 500 subs)\n"
            "Strategy: Maximum variety — cover many different pillars to find what resonates.\n"
            "Avoid repeating any pillar more than twice in this batch.\n"
            "Prioritise topics with the widest possible curiosity appeal."
        )
    elif sub_count < 1000:
        growth_phase = "growth"
        phase_context = (
            "📈 GROWTH PHASE: GROWTH (500–1000 subs)\n"
            "Strategy: Double down on proven pillars. Include 60% topics from top-performing\n"
            "categories and 40% exploratory topics to find new winners.\n"
            "Favour quiz and story formats to boost retention."
        )
    else:
        growth_phase = "monetization"
        phase_context = (
            "💰 GROWTH PHASE: MONETIZATION (1000+ subs)\n"
            "Strategy: Focus on high-RPM education categories: psychology, economics, technology,\n"
            "health/body, history. These attract premium advertisers.\n"
            "Prioritise 'story' and 'quiz' formats for maximum retention and RPM."
        )
    print(f"📍 [RESEARCH] Growth phase: {growth_phase} ({sub_count} subs)")

    sys_msg  = prompts_cfg["researcher"]["system_prompt"]
    user_msg = prompts_cfg["researcher"]["user_template"].format(
        needed_count=max(5, needed + 5),
        niche=prompt_niche,
        channel_context=channel_context + competitor_section,
        history_string=", ".join(historical_topics[-300:]) if historical_topics else "None",
        pillar_context=pillar_context,
        phase_context=phase_context,
    )

    # For factual channels, add a diversity instruction so topics aren't all
    # ocean/space/sea — the operator wants varied random fun facts.
    if is_factual:
        user_msg += (
            f"\n\nVARIETY REQUIREMENT: The topics you generate MUST be diverse. "
            f"Do NOT focus on a single theme (no all-ocean, all-space, all-animals runs). "
            f"Cover a broad mix of categories: psychology, history, food, technology, "
            f"biology, physics, geography, economy, pop culture, nature, human body, "
            f"ordinary objects, weird world records, strange laws, everyday science. "
            f"Avoid repeating a topic category more than twice in this batch."
        )
    
    # ── FICTIONAL channels: force STORY LOGLINES, not abstract topics ─────
    # Root cause of AnimeRise nonsense: the researcher treated fiction lenses
    # like "the secret lives of everyday objects" as literal topics and the LLM
    # emitted one-word/single-noun ideas ("a fork", "a leaf") that the script
    # writer then turned into incoherent vignettes. Fiction needs character-driven
    # loglines with a goal + obstacle + emotional payoff (Pixar formula).
    is_fictional = getattr(channel_config, "content_type", None) == "fictional"

    if is_fictional:
        user_msg += (
            f"\n\n🎭 STORY LOGLINE REQUIREMENT (fiction channel):\n"
            f"Each topic MUST be a complete, character-driven story logline — "
            f"ONE enticing sentence in the Pixar style:\n"
            f"  • Has a named or clearly-imagined PROTAGONIST\n"
            f"  • Gives them a clear GOAL or DESIRE\n"
            f"  • Adds an OBSTACLE or conflict\n"
            f"  • Ends with an emotional/moral payoff (warmth, wonder, irony)\n"
            f"Example: 'A shy robot who collects broken toys learns that "
            f"imperfection is what makes things lovable.'\n"
            f"Example: 'A tiny lighthouse keeper must keep a storm lantern lit "
            f"to guide a lost paper boat home.'\n\n"
            f"STRICTLY FORBIDDEN topics:\n"
            f"  • Single nouns / single words ('a leaf', 'a fork', 'the ocean')\n"
            f"  • Abstract one-liners without a character or event\n"
            f"  • 'The life of X' / 'what if X' factual musings with no story arc\n"
            f"  • Random trivia or facts — this channel tells STORIES\n"
            f"Every topic MUST contain a protagonist, a want, and a conflict."
        )

    if channel_config.creative_lenses:
        lens = random.choice(channel_config.creative_lenses)
        print(f"      🎨 Injecting Channel-Specific Lens: {lens}")
        if is_fictional:
            user_msg += (
                f"\n\nCRITICAL: Transform this Creative Lens into a warm "
                f"character-driven moral-story premise: '{lens}'. "
                f"Use it to seed the PROTAGONIST and WORLD, then invent a "
                f"specific little adventure with a conflict and a resolution. "
                f"Never list the lens as a literal topic."
            )
        else:
            user_msg += f"\n\nCRITICAL: You MUST filter all {needed} ideas through this specific Creative Lens: '{lens}'. Make them bizarre and fascinating."

    raw, _ = quota_manager.generate_text(user_msg, task_type="research", system_prompt=sys_msg)
    if not raw:
        return [], None

    evolved_niche = None
    topics = []
    
    try:
        clean_raw = raw.strip().replace("```json", "").replace("```", "").strip()
        
        if clean_raw.startswith("["):
            start_arr = raw.find('[')
            end_arr = raw.rfind(']')
            if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
                topics = json.loads(raw[start_arr:end_arr+1])
        else:
            start = raw.find('{')
            end = raw.rfind('}')
            if start != -1 and end != -1 and end > start:
                parsed = json.loads(raw[start:end+1])
                if isinstance(parsed, dict):
                    evolved_niche = parsed.get("evolved_niche")
                    topics        = parsed.get("topics", [])
                    
            if not topics:
                start_arr = raw.find('[')
                end_arr = raw.rfind(']')
                if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
                    salvaged = json.loads(raw[start_arr:end_arr+1])
                    if isinstance(salvaged, list): 
                        topics = salvaged
    except Exception as e:
        trace = traceback.format_exc()
        logger.error(f"Failed to parse AI research JSON:\n{trace}")

    return topics, evolved_niche

def run_dynamic_research(channel_config: ChannelConfig, yt_client):
    if not quota_manager.can_afford_youtube(15):
        logger.engine("YT quota too low for research. Skipping.")
        return

    set_channel_context(channel_config)
    logger.research(f"Deep-scanning trends for {channel_config.channel_name}...")

    unprocessed = db.get_unprocessed_count(channel_config.channel_id)
    historical_topics = db.get_all_historical_topics(channel_config.channel_id)

    needed = 21 - unprocessed
    if needed <= 0:
        logger.engine(f"Queue already full ({unprocessed} unprocessed). Skipping research.")
        return

    prompts_cfg = load_config_prompts()
    try:
        from engine.config_manager import config_manager as cm
        settings = cm.get_settings()
    except Exception:
        settings = {}

    channel_context = get_deep_channel_context(yt_client)

    intel = db.get_channel_intelligence(channel_config.channel_id)

    # ── BUG FIX: Anchor sub-niche research to the CONFIGURED niche ────────────
    # Previously this used `intel.get("evolved_niche") or channel_config.niche`.
    # Once the evolved niche drifted (e.g. "trending facts" → "cosmic abyss"),
    # every research run split that drifted string into sub-niches and generated
    # only more cosmic content — a self-reinforcing loop.
    #
    # For FACTUAL channels we now ALWAYS anchor to the configured niche from
    # channels.yaml. This guarantees the researcher produces varied educational /
    # random fun-fact topics regardless of any stored evolved_niche drift.
    # The evolved niche is shown as context but never as the anchor.
    is_factual = getattr(channel_config, "content_type", None) == "factual"
    # FICTIONAL channel flag — used downstream for the story-logl ine quality gate
    # on generated topics and the fiction arc enforcement in script generation.
    is_fictional = getattr(channel_config, "content_type", None) == "fictional"
    if is_factual:
        active_niche_string = channel_config.niche.strip()
        drifted = intel.get("evolved_niche")
        if drifted and drifted != active_niche_string:
            logger.engine(f"📌 [RESEARCH] '{channel_config.channel_name}' — ignoring drifted evolved niche, anchoring to configured niche: '{active_niche_string}'")
    else:
        active_niche_string = intel.get("evolved_niche") or channel_config.niche
    
    sub_niches = [n.strip() for n in active_niche_string.split(', ')] if ',' in active_niche_string else [active_niche_string]
    added_count = 0
    overall_evolved = None
    competitor_summary = ""

    # FIX: Read the Feature Flag to dictate chunking logic
    experimental_lenses = settings.get("research", {}).get("experimental_sub_niche_lenses", False)

    for active_niche in sub_niches:
        if added_count >= needed:
            break
            
        logger.engine(f"🔍 Analyzing sub-niche: {active_niche}")
        competitor_context = ""
        competitor_budget = 100 + (settings.get("intelligence", {}).get("competitor_channels_to_analyze", 3) * 3)
        
        if quota_manager.can_afford_youtube(competitor_budget):
            competitor_context = research_competitors(yt_client, active_niche)
            if competitor_context and not competitor_summary:
                lines = competitor_context.strip().split("\n")
                competitor_summary = lines[0] if lines else ""

        # FIX: Loop and chunk the requests. The random.choice(creative_lenses) inside 
        # _generate_topics_and_evolve_niche will now be called dynamically for every small batch.
        while added_count < needed:
            chunk_size = 5 if experimental_lenses else (needed - added_count)
            chunk_needed = min(chunk_size, needed - added_count)
            
            new_topics, evolved_niche = _generate_topics_and_evolve_niche(
                channel_config, chunk_needed, channel_context, competitor_context,
                historical_topics, prompts_cfg, active_niche
            )
            
            if evolved_niche:
                overall_evolved = evolved_niche

            if not new_topics:
                break # If AI fails to return topics, break out to the next sub-niche

            valid_topics_added_in_chunk = 0

            for item in new_topics:
                if added_count >= needed:
                    break
                
                topic_clean = ""
                topic_hook  = ""
                topic_fmt   = "fact"
                topic_pillar = ""
                if isinstance(item, dict):
                    topic_clean  = item.get("topic",  "").strip()
                    topic_hook   = item.get("hook",   "").strip()
                    topic_fmt    = item.get("format", "fact").strip().lower()
                    topic_pillar = item.get("pillar", "").strip().lower()
                    if topic_fmt not in ("fact", "quiz", "story"):
                        topic_fmt = "fact"
                elif isinstance(item, str):
                    topic_clean = item.strip()
                    
                if not topic_clean:
                    continue
                    
                if any(_jaccard_similarity(topic_clean, h) > 0.6 for h in historical_topics):
                    continue

                # ── FICTIONAL quality gate: reject abstract/nonsense topics ──
                # A fiction channel's topic MUST read like a character-driven
                # logline — ≥5 words, contains an actor/goal verb, and is NOT a
                # bare noun or a 'life of X' musing. Short one-noun topics are
                # exactly the AnimeRise "nonsense" failure mode.
                if is_fictional:
                    if len(topic_clean.split()) < 5:
                        print(f"      ⏭️  Skipping too-short fictional topic: '{topic_clean[:60]}'")
                        continue
                    _low = topic_clean.lower()
                    _bare_noun = (
                        _low.startswith(("a ", "an ", "the ")) and
                        len(_low.split()) <= 3
                    )
                    _fact_musing = any(x in _low for x in (
                        "the life of", "what if", "a fact about", "random fact",
                        "did you know", "interesting fact",
                    ))
                    if _bare_noun or _fact_musing:
                        print(f"      ⏭️  Rejecting non-story fictional topic: '{topic_clean[:60]}'")
                        continue

                validated_niche = active_niche
                import json as _json
                job_metadata = {}
                if topic_hook:
                    job_metadata["hook"] = topic_hook
                    print(f"      🎣 Hook attached: {topic_hook[:80]}")
                if topic_fmt and topic_fmt != "fact":
                    job_metadata["content_format"] = topic_fmt
                    print(f"      📋 Format: {topic_fmt}")
                if topic_pillar:
                    job_metadata["pillar"] = topic_pillar
                    print(f"      🏛️  Pillar: {topic_pillar}")
                db.upsert_job(VideoJob(
                    channel_id=channel_config.channel_id,
                    topic=topic_clean,
                    niche=validated_niche,
                    metadata=_json.dumps(job_metadata) if job_metadata else None,
                ))
                db.archive_topic(channel_config.channel_id, topic_clean, validated_niche)
                historical_topics.append(topic_clean.lower())
                added_count += 1
                valid_topics_added_in_chunk += 1

            # If not chunking, or if the AI returned garbage/duplicates, move on to the next sub-niche
            if not experimental_lenses or valid_topics_added_in_chunk == 0:
                break

    if overall_evolved or competitor_summary:
        # ── BUG FIX: Do NOT persist evolved_niche for FACTUAL channels ─────────
        # The evolution mechanism was designed to let the LLM reshape the niche
        # based on content performance. But for factual channels this caused a
        # compounding drift loop: early cosmic/sea topics made the LLM think the
        # channel's niche was "cosmic abyss", which then anchored all future
        # research to that theme, producing only cosmic/sea content.
        #
        # Fix: factual channels ALWAYS keep their configured niche. The LLM's
        # evolved_niche is logged and discarded — only competitor tags and the
        # other intelligence fields persist.
        is_factual = getattr(channel_config, "content_type", None) == "factual"

        if overall_evolved and overall_evolved != channel_config.niche:
            if is_factual:
                logger.engine(f"🧬 [RESEARCH] Discarding evolved niche for factual channel: '{overall_evolved[:100]}'")
                logger.engine(f"   → Kept configured niche: '{channel_config.niche[:100]}'")
            else:
                intel["evolved_niche"] = overall_evolved
                logger.engine(f"🧬 Niche evolved: '{channel_config.niche}' → '{overall_evolved}'")

        if competitor_summary:
            comp_tags = re.findall(r"#(\w+)", competitor_summary)
            if comp_tags:
                existing = intel.get("competitor_tags", [])
                intel["competitor_tags"] = list(dict.fromkeys(existing + comp_tags))[-30:]

        db.upsert_channel_intelligence(channel_config.channel_id, intel)

    logger.success(f"Added {added_count} unique topics for {channel_config.channel_name}.")
    notify_research_complete(channel_config.channel_name, added_count, active_niche_string, competitor_summary)

if __name__ == "__main__":
    from engine.config_manager import config_manager
    from scripts.youtube_manager import get_youtube_client as yt_auth
    for ch in config_manager.get_active_channels():
        set_channel_context(ch)
        yt = yt_auth(ch)
        run_dynamic_research(ch, yt)