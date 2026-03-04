import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from scripts.discord_notifier import notify_cleanup

def authenticate_drive():
    """
    Authenticates with Google Drive using the User OAuth tokens 
    to bypass the Service Account 0-byte storage quota limit.
    """
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    
    if not all([client_id, client_secret, refresh_token]):
        print("⚠️ OAuth Credentials missing. Drive upload bypassed.")
        return None
    
    try:
        # Create user credentials using the refresh token
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"❌ Failed to authenticate Google Drive via OAuth: {e}")
        return None

def manage_drive_backup(file_path, video_title):
    """
    Uploads the final video to Google Drive and strictly enforces a 5-video limit.
    """
    service = authenticate_drive()
    folder_id = os.environ.get("DRIVE_FOLDER_ID")
    
    if not service or not folder_id:
        return False
        
    if not os.path.exists(file_path):
        return False

    file_name = os.path.basename(file_path)
    
    # --- 1. UPLOAD NEW VIDEO ---
    print(f"☁️ Uploading {file_name} to Google Drive Vault via User OAuth...")
    try:
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print("✅ Successfully uploaded to Drive.")
    except Exception as e:
        print(f"❌ Drive upload failed: {e}")
        return False
        
    # --- 2. AUTO-JANITOR (ENFORCE 5-VIDEO LIMIT) ---
    print("🧹 Checking Vault capacity (Limit: 5 videos)...")
    try:
        query = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(
            q=query,
            orderBy="createdTime",
            fields="files(id, name, createdTime)"
        ).execute()
        
        files = results.get('files', [])
        
        if len(files) > 5:
            excess_count = len(files) - 5
            
            for i in range(excess_count):
                old_file = files[i]
                print(f"🗑️ Deleting oldest backup: {old_file['name']}")
                service.files().delete(fileId=old_file['id']).execute()
                notify_cleanup(old_file['name'], "Vault capacity reached (5 max).")
                
            print("✅ Vault capacity restored.")
        return True
    except Exception as e:
        print(f"❌ Drive cleanup failed: {e}")
        return False
