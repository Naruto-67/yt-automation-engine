# scripts/youtube_manager.py
# Ghost Engine V26.0.0 — High-RPM Monetization Uploader
import os
import pickle
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from engine.logger import logger
from engine.config_manager import config_manager

# V26 Scopes
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

def get_authenticated_service(channel_id):
    """
    V26: Handles token refresh and authentication for specific channels.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    creds_dir = os.path.join(root_dir, "memory", "tokens")
    os.makedirs(creds_dir, exist_ok=True)
    
    token_file = os.path.join(creds_dir, f"token_{channel_id}.pickle")
    creds = None

    if os.path.exists(token_file):
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, 'wb') as token:
                pickle.dump(creds, token)
        else:
            logger.error(f"Credentials for {channel_id} are invalid or missing.")
            return None

    return build('youtube', 'v3', credentials=creds)

def upload_video(file_path, title, description, tags, channel_config):
    """
    Uploads video with V26 target metadata for high RPM.
   
    """
    youtube = get_authenticated_service(channel_config['channel_id'])
    if not youtube: return False

    logger.upload(f"Initiating high-RPM upload for: {title}")

    body = {
        'snippet': {
            'title': title[:100],
            'description': description,
            'tags': tags,
            'categoryId': str(channel_config.get('category_id', '22')),
            'defaultLanguage': channel_config.get('language', 'en'),
            'defaultAudioLanguage': channel_config.get('language', 'en')
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False,
        }
    }

    try:
        media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype='video/mp4')
        request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Upload Progress: {int(status.progress() * 100)}%")

        logger.success(f"Video uploaded successfully! ID: {response['id']}")
        return True
    except Exception as e:
        logger.error(f"YouTube Upload Failed: {e}")
        return False
