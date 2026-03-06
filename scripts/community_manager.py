import os
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager

def run_community_engagement():
    print("💬 [COMMUNITY MANAGER] Waking up. Scanning YouTube for top unanswered comments...")
    youtube = get_youtube_client()
    if not youtube:
        print("⚠️ [COMMUNITY MANAGER] YouTube OAuth missing. Skipping engagement.")
        return

    try:
        # Fetch the channel ID
        channel_response = youtube.channels().list(mine=True, part="id").execute()
        channel_id = channel_response["items"][0]["id"]

        # Fetch recent comments
        request = youtube.commentThreads().list(
            part="snippet,replies",
            allThreadsRelatedToChannelId=channel_id,
            maxResults=20,
            order="time"
        )
        response = request.execute()

        unanswered_comments = []
        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comment_id = item["snippet"]["topLevelComment"]["id"]
            author = snippet["authorDisplayName"]
            text = snippet["textOriginal"]
            
            # Check if we already replied (totalReplyCount == 0)
            if item["snippet"]["totalReplyCount"] == 0:
                unanswered_comments.append({"id": comment_id, "author": author, "text": text})

        print(f"🔍 [COMMUNITY MANAGER] Found {len(unanswered_comments)} unanswered comments.")

        for comment in unanswered_comments:
            print(f"\n   👤 {comment['author']} says: '{comment['text']}'")
            
            prompt = f"""
            You are a popular, high-energy YouTube Shorts creator. 
            A fan named '{comment['author']}' just left this comment on your video: "{comment['text']}"
            
            Write a short, engaging, and highly appreciative reply. Keep it under 2 sentences. Use emojis.
            Do not use generic corporate speak. Be human and fun.
            Return ONLY the reply text, nothing else.
            """
            
            # 🚨 Routes strictly to Groq to save Gemini quota
            reply_text, provider = quota_manager.generate_text(prompt, task_type="comment_reply")
            
            if reply_text:
                print(f"   🤖 Groq Drafts Reply: '{reply_text.strip()}'")
                # When TEST_MODE is disabled later, we will inject the actual youtube.comments().insert() call here
                print("   🛑 [TEST MODE] Reply generation successful. Skipping actual YouTube POST.")
                
    except Exception as e:
        print(f"❌ [COMMUNITY MANAGER] Failed to fetch or reply to comments: {e}")

if __name__ == "__main__":
    run_community_engagement()
