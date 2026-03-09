# scripts/dynamic_researcher.py — Ghost Engine V6
import re
import json
import yaml
import os
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import (
    set_channel_context, notify_research_complete, notify_summary
)
from engine.database import db
from engine.models import VideoJob, ChannelConfig
from engine.logger import logger


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
    """
    Fetches own channel's top-performing videos for research context.
    Uses ONLY last 30 days for recency — not all-time.
    Cost: ~3 YT pts.
    """
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

        vid_ids = [v["snippet"]["resourceId"]["videoId"]
                   for v in vids.get("items", [])]
        if not vid_ids:
            return "Brand new channel — generate broad content."

        stats = youtube.videos().list(
            part="statistics,snippet", id=",".join(vid_ids)
        ).execute()
        quota_manager.consume_points("youtube", 1)

        # Recency-weighted: only videos from last 30 days
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()

        video_data = sorted([
            {
                "title":        i["snippet"]["title"],
                "views":        int(i["statistics"].get("viewCount", 0)),
                "published_at": i["snippet"].get("publishedAt", ""),
            }
            for i in stats.get("items", [])
            if i["snippet"].get("publishedAt", "") > cutoff
        ], key=lambda x: x["views"], reverse=True)

        if not video_data:
            # Fall back to all-time top 3
            video_data = sorted([
                {"title": i["snippet"]["title"],
                 "views": int(i["statistics"].get("viewCount", 0))}
                for i in stats.get("items", [])
            ], key=lambda x: x["views"], reverse=True)[:3]

        return "📊 Top Recent Content (last 30 days):\n" + "\n".join([
            f"- '{v['title']}' | {v['views']:,} views"
            for v in video_data[:5]
        ])
    except Exception as e:
        logger.error(f"Channel context fetch failed: {e}")
        return "Generate broad niches."


def research_competitors(youtube, niche: str, top_n: int = 3) -> str:
    """
    Finds top competitor channels in the same niche and extracts insights.
    Used to evolve content strategy.
    Cost: ~1 YT pt (search.list) + top_n × 2 pts
    """
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
        # Search for top channels in this niche
        search = youtube.search().list(
            part="snippet", type="channel", q=niche,
            order="relevance", maxResults=top_n
        ).execute()
        quota_manager.consume_points("youtube", 100)  # search.list = 100 pts

        competitor_ids = [
            item["snippet"]["channelId"]
            for item in search.get("items", [])
            if "channelId" in item["snippet"]
        ]
        if not competitor_ids:
            return ""

        insights = []
        for ch_id in competitor_ids[:top_n]:
            try:
                # Get uploads playlist
                ch_res = youtube.channels().list(
                    part="contentDetails,snippet", id=ch_id
                ).execute()
                quota_manager.consume_points("youtube", 1)

                if not ch_res.get("items"):
                    continue

                ch_name    = ch_res["items"][0]["snippet"]["title"]
                uploads_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

                pl_items = youtube.playlistItems().list(
                    part="snippet", playlistId=uploads_id, maxResults=top_vids
                ).execute()
                quota_manager.consume_points("youtube", 1)

                vid_ids = [v["snippet"]["resourceId"]["videoId"]
                           for v in pl_items.get("items", [])]
                if not vid_ids:
                    continue

                vids = youtube.videos().list(
                    part="statistics,snippet", id=",".join(vid_ids)
                ).execute()
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
                    insights.append(
                        f"Channel: {ch_name}\n" +
                        "\n".join([
                            f"  - '{t['title']}' | {t['views']:,} views"
                            for t in top_titles
                        ])
                    )
            except Exception:
                continue

        return "\n\n".join(insights)

    except Exception as e:
        logger.error(f"Competitor research failed: {e}")
        return ""


def _generate_topics_and_evolve_niche(
    channel_config: ChannelConfig,
    needed: int,
    channel_context: str,
    competitor_context: str,
    historical_topics: list,
    prompts_cfg: dict
) -> tuple:
    """
    Calls AI to generate topics AND optionally evolve the niche.
    Returns (topics: list[dict], evolved_niche: str | None)
    """
    intel = db.get_channel_intelligence(channel_config.channel_id)

    # Build enhanced research prompt that includes competitor insights
    competitor_section = (
        f"\n\n🏆 COMPETITOR INSIGHTS (Study these winning patterns):\n{competitor_context}"
        if competitor_context else ""
    )

    sys_msg  = prompts_cfg["researcher"]["system_prompt"]
    user_msg = prompts_cfg["researcher"]["user_template"].format(
        needed_count=max(5, needed + 5),
        niche=channel_config.niche,
        channel_context=channel_context + competitor_section,
        history_string=", ".join(historical_topics[-30:]) if historical_topics else "None"
    )

    raw, _ = quota_manager.generate_text(user_msg, task_type="research",
                                          system_prompt=sys_msg)
    if not raw:
        return [], None

    # Try to also extract an evolved niche suggestion
    evolved_niche = None
    try:
        parsed = json.loads(raw.replace("```json", "").replace("```", "").strip())
        if isinstance(parsed, dict):
            evolved_niche = parsed.get("evolved_niche")
            topics        = parsed.get("topics", [])
        else:
            topics = parsed
    except Exception:
        topics = []
        # Try regex extraction as fallback
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            try:
                topics = json.loads(match.group(0))
            except Exception:
                pass

    return topics, evolved_niche


def run_dynamic_research(channel_config: ChannelConfig, yt_client):
    """
    Main weekly/on-demand research function.
    Fills topic queue, researches competitors, optionally evolves niche.
    """
    if not quota_manager.can_afford_youtube(15):
        logger.engine("YT quota too low for research. Skipping.")
        return

    set_channel_context(channel_config)
    logger.research(f"Deep-scanning trends for {channel_config.channel_name}...")

    unprocessed      = db.get_unprocessed_count(channel_config.channel_id)
    historical_topics = db.get_all_topics(channel_config.channel_id)

    needed = 21 - unprocessed
    if needed <= 0:
        logger.engine(f"Queue already full ({unprocessed} unprocessed). Skipping research.")
        return

    prompts_cfg = load_config_prompts()
    settings    = config_manager.get_settings() if False else {}
    try:
        from engine.config_manager import config_manager as cm
        settings = cm.get_settings()
    except Exception:
        pass

    # Gather own channel context (recency-weighted)
    channel_context = get_deep_channel_context(yt_client)

    # Research competitors if we have enough quota budget
    competitor_context = ""
    # Competitor search costs 100 YT pts (search.list) + ~3 pts per channel
    competitor_budget = 100 + (settings.get("intelligence", {}).get(
        "competitor_channels_to_analyze", 3) * 3)
    if quota_manager.can_afford_youtube(competitor_budget):
        competitor_context = research_competitors(yt_client, channel_config.niche)
    else:
        logger.engine("Skipping competitor research (quota budget insufficient).")

    # Generate topics
    new_topics, evolved_niche = _generate_topics_and_evolve_niche(
        channel_config, needed, channel_context, competitor_context,
        historical_topics, prompts_cfg
    )

    if not new_topics:
        logger.error(f"Research cycle returned no topics for {channel_config.channel_id}.")
        return

    # Insert unique topics into DB
    added_count = 0
    for item in new_topics:
        if added_count >= needed:
            break
        topic_clean = item.get("topic", "").strip()
        if not topic_clean:
            continue
        # Jaccard deduplication
        if any(_jaccard_similarity(topic_clean, h) > 0.6 for h in historical_topics):
            continue

        db.upsert_job(VideoJob(
            channel_id=channel_config.channel_id,
            topic=topic_clean,
            niche=item.get("niche", channel_config.niche)
        ))
        historical_topics.append(topic_clean.lower())
        added_count += 1

    # Update channel intelligence with competitor findings
    if competitor_context or evolved_niche:
        intel = db.get_channel_intelligence(channel_config.channel_id)

        if evolved_niche and evolved_niche != channel_config.niche:
            intel["evolved_niche"] = evolved_niche
            logger.engine(
                f"🧬 Niche evolved: '{channel_config.niche}' → '{evolved_niche}'"
            )

        if competitor_context:
            # Extract competitor tags from the context (simple heuristic)
            comp_tags = re.findall(r"#(\w+)", competitor_context)
            if comp_tags:
                existing = intel.get("competitor_tags", [])
                intel["competitor_tags"] = list(
                    dict.fromkeys(existing + comp_tags)
                )[-30:]

        db.upsert_channel_intelligence(channel_config.channel_id, intel)

    logger.success(f"Added {added_count} unique topics for {channel_config.channel_name}.")

    # Summarise competitor insight for Discord notification
    competitor_summary = ""
    if competitor_context:
        lines = competitor_context.strip().split("\n")
        competitor_summary = lines[0] if lines else ""

    active_niche = (
        db.get_channel_intelligence(channel_config.channel_id).get("evolved_niche")
        or channel_config.niche
    )

    notify_research_complete(
        channel_config.channel_name,
        added_count,
        active_niche,
        competitor_summary
    )


if __name__ == "__main__":
    from engine.config_manager import config_manager
    from scripts.youtube_manager import get_youtube_client as yt_auth
    for ch in config_manager.get_active_channels():
        set_channel_context(ch)
        yt = yt_auth(ch)
        run_dynamic_research(ch, yt)
