# scripts/reply_comments.py
# ═══════════════════════════════════════════════════════════════════════════════
# FIX #5 — Comment reply deduplication
#
# BUG: The engagement workflow runs daily. It fetched the most-relevant comments
# on recent videos and replied to unreplied ones. But there was no memory of
# which comment IDs had already been replied to. Old, unresolved comments (e.g.
# comments on older videos that didn't get a reply that day) could be replied to
# again on subsequent days, making the channel look spammy.
#
# FIX: memory/replied_comments.json stores a set of comment thread IDs that
# have already received a reply. Before inserting any reply, we check this set.
# After inserting, we add the ID to the set and persist it.
#
# PRUNING: The set is capped at 5,000 IDs and old entries are pruned when
# the cap is exceeded. Comments older than ~30 days are unlikely to resurface
# in the 'most relevant' results anyway.
#
# FIX #8 (PARTIAL) — Kill switch Python-level guard added here.
# ═══════════════════════════════════════════════════════════════════════════════

import os
import json
import time
import random
import sys
import yaml
from scripts.quota_manager import quota_manager
from scripts.youtube_manager import get_youtube_client
from scripts.discord_notifier import notify_summary
from engine.config_manager import config_manager


# ── Kill switch (Fix #8 defence-in-depth) ────────────────────────────────────
_ENABLED = os.environ.get("GHOST_ENGINE_ENABLED", "true").strip().lower()
if _ENABLED == "false":
    print("🔴 [KILL SWITCH] GHOST_ENGINE_ENABLED=false. Engagement halted.")
    sys.exit(0)


# ── Deduplication store ───────────────────────────────────────────────────────
REPLIED_FILE = os.path.join(os.path.dirname(__file__), "..", "memory", "replied_comments.json")
MAX_STORED   = 5000  # Prune when we exceed this to keep the file small


def _load_replied() -> set:
    """Load the set of already-replied comment thread IDs from disk."""
    if os.path.exists(REPLIED_FILE):
        try:
            with open(REPLIED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("replied_ids", []))
        except Exception:
            pass
    return set()


def _save_replied(replied_ids: set):
    """Persist the deduplication set. Prunes oldest entries beyond MAX_STORED."""
    os.makedirs(os.path.dirname(REPLIED_FILE), exist_ok=True)
    ids_list = list(replied_ids)
    if len(ids_list) > MAX_STORED:
        # Prune: keep the most recent MAX_STORED entries
        # Sets are unordered, so we just slice — any pruning is acceptable
        ids_list = ids_list[-MAX_STORED:]
    with open(REPLIED_FILE, "w", encoding="utf-8") as f:
        json.dump({"replied_ids": ids_list}, f)


def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_ai_reply(video_title, comment_text, attempt_num, prompts_cfg):
    sys_msg  = prompts_cfg["replier"]["system_prompt"]
    user_msg = prompts_cfg["replier"]["user_template"].format(
        comment=str(comment_text)[:500].replace('"', "'"),
        title=video_title,
    )
    raw_reply, _ = quota_manager.generate_text(
        user_msg,
        task_type="comment_reply_groq" if attempt_num > 3 else "creative",
        system_prompt=sys_msg,
    )
    if raw_reply:
        clean = raw_reply.strip().replace('"', "")
        return None if "FLAGGED_COMMENT" in clean else clean
    return None


def run_engagement_protocol():
    prompts_cfg = load_config_prompts()

    # ── FIX #5: Load deduplication set once before the channel loop ──────────
    replied_ids = _load_replied()
    new_replies = 0  # Track how many new replies we added this run
    # ─────────────────────────────────────────────────────────────────────────

    for channel in config_manager.get_active_channels():
        youtube = get_youtube_client(channel.youtube_refresh_token_env)
        if not youtube:
            continue

        try:
            channel_info = youtube.channels().list(
                part="id,contentDetails", mine=True
            ).execute()
            channel_yt_id = channel_info["items"][0]["id"]
            uploads_pl    = channel_info["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            vids = youtube.playlistItems().list(
                part="snippet", playlistId=uploads_pl, maxResults=5
            ).execute()

            replies_count = 0

            for vid in vids.get("items", []):
                vid_id    = vid["snippet"]["resourceId"]["videoId"]
                vid_title = vid["snippet"]["title"]

                comments = youtube.commentThreads().list(
                    part="snippet", videoId=vid_id, maxResults=15, order="relevance"
                ).execute()

                for thread in comments.get("items", []):
                    top       = thread["snippet"]["topLevelComment"]["snippet"]
                    thread_id = thread["id"]

                    # Skip our own comments
                    if top.get("authorChannelId", {}).get("value") == channel_yt_id:
                        continue

                    # Skip already-replied threads
                    if thread["snippet"]["totalReplyCount"] > 0:
                        continue

                    # ── FIX #5: Skip if we already replied to this thread ─────
                    if thread_id in replied_ids:
                        print(f"⏭️  [ENGAGE] Skipping already-replied thread: {thread_id}")
                        continue
                    # ─────────────────────────────────────────────────────────

                    if not quota_manager.can_afford_youtube(50):
                        break

                    reply_text = generate_ai_reply(vid_title, top["textDisplay"], replies_count + 1, prompts_cfg)
                    if reply_text:
                        youtube.comments().insert(
                            part="snippet",
                            body={"snippet": {"parentId": thread_id, "textOriginal": reply_text}},
                        ).execute()

                        # ── FIX #5: Mark as replied immediately after insert ──
                        replied_ids.add(thread_id)
                        new_replies += 1
                        # ─────────────────────────────────────────────────────

                        replies_count += 1
                        quota_manager.consume_points("youtube", 50)
                        time.sleep(4)

                if replies_count >= random.randint(10, 15):
                    break

            if replies_count > 0:
                notify_summary(True, f"💬 Engaged {replies_count} comments on {channel.channel_name}.")

        except Exception as e:
            print(f"⚠️ [ENGAGE] Error on {channel.channel_name}: {e}")

    # ── FIX #5: Persist the updated deduplication set after all channels ──────
    if new_replies > 0:
        _save_replied(replied_ids)
        print(f"✅ [ENGAGE] Saved {len(replied_ids)} total replied IDs to {REPLIED_FILE}")
    # ─────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    run_engagement_protocol()
