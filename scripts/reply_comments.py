# scripts/reply_comments.py
# Ghost Engine V26.0.0 — Personality-Driven Engagement & Safety Logic
import os
import json
import time
import random
import yaml
from scripts.quota_manager import quota_manager
from scripts.youtube_manager import get_youtube_client
from scripts.discord_notifier import set_channel_context, notify_engagement_report, notify_security_flag, notify_summary
from engine.config_manager import config_manager
from engine.logger import logger

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
_MAX_STORED_IDS = 15000

def _get_replied_path(channel_id: str) -> str:
    return os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        "memory", f"replied_comments_{channel_id}.json"
    )

def _load_replied(channel_id: str) -> list:
    """Loads the list of comment IDs already processed to avoid duplication. [cite: 456]"""
    path = _get_replied_path(channel_id)
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                return list(data) if isinstance(data, list) else list(set(data))
    except Exception:
        pass
    return []

def _save_replied(channel_id: str, replied_list: list):
    """Saves the reply state with a 15,000 ID cap to prevent memory bloat. [cite: 457]"""
    path = _get_replied_path(channel_id)
    try:
        if len(replied_list) > _MAX_STORED_IDS:
            replied_list = replied_list[-_MAX_STORED_IDS:]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(replied_list, f)
    except Exception as e:
        logger.error(f"Failed to save reply state: {e}")

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)

def generate_ai_reply(video_title: str, comment_text: str, personality: str, prompts_cfg: dict):
    """
    V26: Generates a reply based on the channel's unique personality. [cite: 458-459]
    """
    sys_msg  = prompts_cfg["replier"]["system_prompt"]
    # We inject the personality directly into the engagement request
    user_msg = f"PERSONALITY: {personality}\n" + prompts_cfg["replier"]["user_template"].format(
        comment=str(comment_text)[:500].replace('"', "'"), 
        title=video_title
    )
    
    raw, _ = quota_manager.generate_text(user_msg, task_type="creative", system_prompt=sys_msg)
    
    if raw:
        clean = raw.strip().replace('"', "")
        if "FLAGGED_COMMENT" in clean:
            return "FLAGGED"
        return clean
    return "API_FAIL"

def run_engagement_protocol():
    """Main loop for community engagement and monetization protection. [cite: 460-480]"""
    settings    = config_manager.get_settings()
    eng         = settings.get("engagement", {})
    max_replies = eng.get("max_replies_per_channel_per_day", 10)
    max_vids    = eng.get("max_videos_to_scan", 5)
    max_cmts    = eng.get("max_comments_per_video", 10)
    prompts_cfg = load_config_prompts()

    for channel in config_manager.get_active_channels():
        set_channel_context(channel)
        if not quota_manager.can_afford_youtube(55): continue

        youtube = None if TEST_MODE else get_youtube_client(channel)
        if not youtube: continue
       
        replied_ids = _load_replied(channel.channel_id)

        try:
            # Identity check [cite: 461-462]
            ch_res = youtube.channels().list(part="id,contentDetails", mine=True).execute()
            quota_manager.consume_points("youtube", 1)
            channel_yt_id = ch_res["items"][0]["id"]
            uploads_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            # Scan recent public uploads [cite: 463-464]
            vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
            quota_manager.consume_points("youtube", 1)
            vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
            
            stats = youtube.videos().list(part="snippet,status", id=",".join(vid_ids)).execute()
            quota_manager.consume_points("youtube", 1)

            public_vids = [i for i in stats.get("items", []) if i.get("status", {}).get("privacyStatus") == "public"][:max_vids]

            replies_sent = 0
            flagged_count = 0

            for vid in public_vids:
                if replies_sent >= max_replies: break

                comments = youtube.commentThreads().list(part="snippet", videoId=vid["id"], maxResults=max_cmts, order="time").execute()
                quota_manager.consume_points("youtube", 1)

                for thread in comments.get("items", []):
                    if replies_sent >= max_replies: break
                    thread_id = thread["id"]
                    if thread_id in replied_ids: continue

                    top = thread["snippet"]["topLevelComment"]["snippet"]
                    # Skip if the comment is from the channel owner or already has replies [cite: 468-469]
                    if top.get("authorChannelId", {}).get("value", "") == channel_yt_id: continue
                    if thread["snippet"]["totalReplyCount"] > 0:
                        replied_ids.append(thread_id)
                        continue

                    # Generate Personality-Driven Reply [cite: 470-471]
                    reply_text = generate_ai_reply(vid["snippet"]["title"], top["textDisplay"], channel.personality, prompts_cfg)

                    if reply_text == "FLAGGED":
                        flagged_count += 1
                        notify_security_flag(top.get("authorDisplayName", "unknown"), top["textDisplay"][:200], vid["snippet"]["title"])
                        replied_ids.append(thread_id)
                        continue
                    elif reply_text == "API_FAIL":
                        break
                    elif reply_text:
                        # Post Reply [cite: 474-475]
                        youtube.comments().insert(
                            part="snippet",
                            body={"snippet": {"parentId": thread_id, "textOriginal": reply_text}}
                        ).execute()
                        quota_manager.consume_points("youtube", 50)
                        
                        replied_ids.append(thread_id)
                        replies_sent += 1
                        time.sleep(random.uniform(3, 6))

            _save_replied(channel.channel_id, replied_ids)
            notify_engagement_report(replies_sent, flagged_count)
            logger.success(f"Engaged {replies_sent} comments on {channel.channel_name}.")

        except Exception as e:
            logger.error(f"Engagement failed for {channel.channel_id}: {e}")

if __name__ == "__main__":
    run_engagement_protocol()
