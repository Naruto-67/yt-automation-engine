import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def authenticate_drive():
    """
    Authenticates with the Google Drive API using Phase 0 credentials.
    """
    creds_json_str = os.environ.get("GCP_CREDENTIALS_JSON")
    if not creds_json_str:
        print("⚠️ GCP_CREDENTIALS_JSON missing. Drive upload bypassed.")
        return None
    
    try:
        creds_dict = json.loads(creds_json_str)
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict, 
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        print(f"❌ Failed to authenticate Google Drive: {e}")
        return None

def manage_drive_backup(file_path):
    """
    Uploads the final video to Google Drive and strictly enforces a 5-video limit.
    """
    service = authenticate_drive()
    folder_id = os.environ.get("DRIVE_FOLDER_ID")
    
    if not service or not folder_id:
        print("⚠️ Drive integration bypassed due to missing credentials or folder ID.")
        return False
        
    if not os.path.exists(file_path):
        print(f"❌ File not found for upload: {file_path}")
        return False

    file_name = os.path.basename(file_path)
    
    # --- 1. UPLOAD THE NEW VIDEO ---
    print(f"☁️ Uploading {file_name} to Google Drive Vault...")
    try:
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
        
        uploaded_file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id'
        ).execute()
        
        print(f"✅ Successfully uploaded to Drive. File ID: {uploaded_file.get('id')}")
    except Exception as e:
        print(f"❌ Drive upload failed: {e}")
        return False
        
    # --- 2. THE AUTO-JANITOR (ENFORCE 5-VIDEO LIMIT) ---
    print("🧹 Checking Vault capacity (Limit: 5 videos)...")
    try:
        # Query files in the specific folder, sorting by oldest first
        query = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(
            q=query,
            orderBy="createdTime",
            fields="files(id, name, createdTime)"
        ).execute()
        
        files = results.get('files', [])
        
        if len(files) > 5:
            excess_count = len(files) - 5
            print(f"⚠️ Vault has {len(files)} files. Deleting the oldest {excess_count}...")
            
            # Since it's sorted oldest first, we delete the first 'excess_count' files
            for i in range(excess_count):
                old_file = files[i]
                print(f"🗑️ Deleting oldest backup: {old_file['name']}")
                service.files().delete(fileId=old_file['id']).execute()
                
            print("✅ Vault capacity restored to exactly 5 videos.")
        else:
            print(f"✅ Vault capacity is good ({len(files)}/5).")
            
        return True
    except Exception as e:
        print(f"❌ Drive cleanup failed: {e}")
        return False

if __name__ == "__main__":
    # Local execution test
    print("Testing Google Drive Connection...")
    auth_test = authenticate_drive()
    if auth_test:
        print("✅ Connection Successful! The Vault is accessible.")
