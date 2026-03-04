import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz

def get_google_sheet():
    """
    Authenticates and connects to your Google Sheet using Phase 0 secure credentials.
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Pulling the exact Phase 0 credentials you provided
    creds_json_str = os.environ.get("GCP_CREDENTIALS_JSON")
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID") 
    
    if not creds_json_str or not sheet_id:
        print("⚠️ Warning: GCP_CREDENTIALS_JSON or GOOGLE_SHEETS_ID missing. Logger bypassed.")
        return None
        
    try:
        creds_dict = json.loads(creds_json_str)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # Locks onto your exact sheet using the ID
        sheet = client.open_by_key(sheet_id).sheet1
        return sheet
    except Exception as e:
        print(f"❌ Failed to connect to Google Sheets: {e}")
        return None

def is_script_duplicate(script_hook):
    """
    Scans the Google Sheet to see if the AI has used this exact script hook before.
    Returns True if it exists, False if it is brand new.
    """
    sheet = get_google_sheet()
    if not sheet:
        return False 
        
    try:
        # We assume the unique script hook/topic is logged in Column C (Index 3)
        existing_hooks = sheet.col_values(3)
        
        hook_lower = script_hook.lower().strip()
        for existing in existing_hooks:
            if hook_lower in existing.lower().strip():
                print(f"🛑 DUPLICATE DETECTED: The AI tried to use a similar script. Regenerating...")
                return True
                
        return False
    except Exception as e:
        print(f"⚠️ Error checking duplicates: {e}")
        return False

def log_completed_video(niche, script_hook, filename):
    """
    Writes a permanent record of the successful video into the Google Sheet.
    """
    sheet = get_google_sheet()
    if not sheet:
        return False
        
    try:
        # Updated to India Standard Time (IST)
        ist_timezone = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(ist_timezone).strftime("%Y-%m-%d %H:%M:%S")
        
        # Append a new row: [Date, Niche, Script Hook (Topic), Filename, Status]
        row_data = [current_time, niche.upper(), script_hook, filename, "RENDERED"]
        sheet.append_row(row_data)
        
        print(f"✅ Successfully logged video to Google Sheets.")
        return True
    except Exception as e:
        print(f"❌ Failed to write to Google Sheets: {e}")
        return False

if __name__ == "__main__":
    # Local testing execution
    print("Testing Phase 0 Logger Connection...")
    test_sheet = get_google_sheet()
    if test_sheet:
        print("✅ Connection Successful! The AI now has a memory.")
