# scripts/reply_comments.py — Ghost Engine V6
import os
import json
import time
import random
import yaml
from scripts.quota_manager import quota_manager
from scripts.youtube_manager import get_youtube_client
from scripts.discord_notifier import (
    set_channel_context, notify_engagement_report,
    notify_security_flag, notify_summary
)
from engine.config_manager import config_manager
from engine.logger import logger

# Path to the deduplication store (committed to repo)
_REPLIED_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "memory", "replied_comments.json"
)
_MAX_STORED_IDS = 5000   # Cap to prevent unbounded growth


def _load_replied() -> set:
    try:
        if os.path.exists(_REPLIED_PATH):
            with open(_REPLIED_PATH, "r") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()


def _save_replied(replied: set):
    try:
        ids = list(replied)
        if len(ids) > _MAX_STORED_IDS:
            ids = ids[-_MAX_STORED_IDS:]   # Keep most recent
        os.makedirs(os.path.dirname(_REPLIED_PATH), exist_ok=True)
        with open(_REPLIED_PATH, "w") as f:
            json.dump(ids, f)
    except Exception as e:
        print(f"⚠️ [REPLY] Failed to save replied_comments.json: {e}")


def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)


def generate_ai_reply(video_title: str, comment_text: str,
                       attempt_num: int, prompts_cfg: dict):
    sys_msg  = prompts_cfg["replier"]["system_prompt"]
    user_msg = prompts_cfg["replier"]["user_template"].format(
        comment=str(comment_text)[:500].replace('"', "'"),
        title=video_title
    )
    task = "comment_reply_groq" if attempt_num > 3 else "creative"
    raw, _ = quota_manager.generate_text(user_msg, task_type=task, system_prompt=sys_msg)
    if raw:
        clean = raw.strip().replace('"', "")
        return None if "FLAGGED_COMMENT" in clean else clean
    return None


def run_engagement_protocol():
    """
    Replies to unreplied fan comments.

    Quota budget:
      - commentThreads.list: 1pt per video (max 5 videos = 5pts)
      - comments.insert:    50pt per reply (max 10 replies = 500pts)
      - Total max: ~505 YT pts per channel per day

    FIX: Per-channel Discord routing via set_channel_context().
    FIX: Deduplication via replied_comments.json.
    FIX: Hard budget cap from settings.yaml engagement.max_replies_per_channel_per_day.
    """
    if os.environ.get("GHOST_ENGINE_ENABLED", "true").lower() == "false":
        print("🔴 [KILL SWITCH] Engagement halted.")
        return

    settings    = config_manager.get_settings()
    eng         = settings.get("engagement", {})
    max_replies = eng.get("max_replies_per_channel_per_day", 10)
    max_vids    = eng.get("max_videos_to_scan", 5)
    max_cmts    = eng.get("max_comments_per_video", 10)

    prompts_cfg = load_config_prompts()
    replied_ids = _load_replied()

    for channel in config_manager.get_active_channels():
        # Set Discord context
        set_channel_context(channel)

        # Budget check: need enough for at least 1 comment insert (50pt)
        if not quota_manager.can_afford_youtube(55):
            logger.engine(f"YT quota too low for engagement on {channel.channel_id}.")
            continue

        youtube = get_youtube_client(channel)
        if not youtube:
            continue

        try:
            ch_res = youtube.channels().list(
                part="id,contentDetails", mine=True
            ).execute()
            quota_manager.consume_points("youtube", 1)

            channel_yt_id = ch_res["items"][0]["id"]
            uploads_id    = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            vids = youtube.playlistItems().list(
                part="snippet", playlistId=uploads_id, maxResults=max_vids
            ).execute()
            quota_manager.consume_points("youtube", 1)

            replies_sent = 0
            flagged_count = 0

            for vid in vids.get("items", []):
                if replies_sent >= max_replies:
                    break

                vid_id    = vid["snippet"]["resourceId"]["videoId"]
                vid_title = vid["snippet"].get("title", "our video")

                comments = youtube.commentThreads().list(
                    part="snippet", videoId=vid_id,
                    maxResults=max_cmts, order="relevance"
                ).execute()
                quota_manager.consume_points("youtube", 1)

                for thread in comments.get("items", []):
                    if replies_sent >= max_replies:
                        break

                    thread_id = thread["id"]
                    # Skip already-replied threads
                    if thread_id in replied_ids:
                        continue

                    top    = thread["snippet"]["topLevelComment"]["snippet"]
                    author = top.get("authorChannelId", {}).get("value", "")

                    # Skip own comments and already-replied threads
                    if author == channel_yt_id:
                        continue
                    if thread["snippet"]["totalReplyCount"] > 0:
                        # Thread already has replies — check if it was us
                        replied_ids.add(thread_id)
                        continue

                    # Quota check before each reply
                    if not quota_manager.can_afford_youtube(50):
                        logger.engine("YT quota insufficient for more replies. Stopping.")
                        break

                    reply_text = generate_ai_reply(
                        vid_title,
                        top["textDisplay"],
                        replies_sent + 1,
                        prompts_cfg
                    )

                    if reply_text is None:
                        flagged_count += 1
                        notify_security_flag(
                            top.get("authorDisplayName", "unknown"),
                            top["textDisplay"][:200],
                            vid_title
                        )
                        replied_ids.add(thread_id)
                        continue

                    try:
                        youtube.comments().insert(
                            part="snippet",
                            body={"snippet": {
                                "parentId":     thread_id,
                                "textOriginal": reply_text
                            }}
                        ).execute()
                        quota_manager.consume_points("youtube", 50)
                        replied_ids.add(thread_id)
                        replies_sent += 1
                        time.sleep(random.uniform(3, 6))   # Human pacing
                    except Exception as e:
                        logger.error(f"Reply failed: {e}")

            _save_replied(replied_ids)
            notify_engagement_report(replies_sent, flagged_count)
            logger.success(
                f"Engaged {replies_sent} comments on {channel.channel_name}. "
                f"Flagged: {flagged_count}."
            )

        except Exception as e:
            logger.error(f"Engagement failed for {channel.channel_id}: {e}")

    _save_replied(replied_ids)


if __name__ == "__main__":
    run_engagement_protocol()
