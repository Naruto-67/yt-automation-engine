import os
import time
import random
import yaml
from scripts.quota_manager import quota_manager
from scripts.youtube_manager import get_youtube_client
from scripts.discord_notifier import notify_summary
from engine.config_manager import config_manager

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f: return yaml.safe_load(f)

def generate_ai_reply(video_title, comment_text, attempt_num, prompts_cfg):
    sys_msg = prompts_cfg['replier']['system_prompt']
    user_msg = prompts_cfg['replier']['user_template'].format(comment=str(comment_text)[:500].replace('"', "'"), title=video_title)

    raw_reply, _ = quota_manager.generate_text(user_msg, task_type="comment_reply_groq" if attempt_num > 3 else "creative", system_prompt=sys_msg)
    if raw_reply:
        clean = raw_reply.strip().replace('"', '')
        return None if "FLAGGED_COMMENT" in clean else clean
    return None

def run_engagement_protocol():
    prompts_cfg = load_config_prompts()
    for channel in config_manager.get_active_channels():
        youtube = get_youtube_client(channel.youtube_refresh_token_env)
        if not youtube: continue

        try:
            channel_id = youtube.channels().list(part="id,contentDetails", mine=True).execute()["items"][0]["id"]
            uploads = youtube.channels().list(part="id,contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            vids = youtube.playlistItems().list(part="snippet", playlistId=uploads, maxResults=5).execute()
            
            replies_count = 0
            for vid in vids.get("items", []):
                vid_id = vid["snippet"]["resourceId"]["videoId"]
                comments = youtube.commentThreads().list(part="snippet", videoId=vid_id, maxResults=15, order="relevance").execute()
                for thread in comments.get("items", []):
                    top = thread["snippet"]["topLevelComment"]["snippet"]
                    if top.get("authorChannelId", {}).get("value") != channel_id and thread["snippet"]["totalReplyCount"] == 0:
                        if not quota_manager.can_afford_youtube(50): break
                        
                        reply_text = generate_ai_reply(vid["snippet"]["title"], top["textDisplay"], replies_count + 1, prompts_cfg)
                        if reply_text:
                            youtube.comments().insert(part="snippet", body={"snippet": {"parentId": thread["id"], "textOriginal": reply_text}}).execute()
                            replies_count += 1
                            quota_manager.consume_points("youtube", 50)
                            time.sleep(4)
                if replies_count >= random.randint(10, 15): break
            if replies_count > 0: notify_summary(True, f"Engaged {replies_count} comments on {channel.channel_name}.")
        except: pass

if __name__ == "__main__": run_engagement_protocol()
