import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz

def get_google_sheet():
    """
    Authenticates and connects to your Google Sheet using the secure credentials stored in GitHub Secrets.
    """
    # Define the scope of access
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Read the secure credentials JSON string from GitHub Secrets
    creds_json_str = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    
    if not creds_json_str:
        print("⚠️  Warning: GOOGLE_SHEETS_CREDENTIALS not found in environment. Logger disabled.")
        return None
        
    try:
        creds_dict = json.loads(creds_json_str)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # Replace this with the exact name of your Google Sheet
        sheet = client.open("YouTube_Automation_Logs").sheet1
        return sheet
    except Exception as e:
        print(f"❌ Failed to connect to Google Sheets: {e}")
        return None

def is_topic_duplicate(topic):
    """
    Scans the Google Sheet to see if this topic has already been covered.
    Returns True if it exists, False if it is brand new.
    """
    sheet = get_google_sheet()
    if not sheet:
        return False # If sheet fails, let the factory run anyway (the show must go on)
        
    try:
        # Assuming Topic is logged in Column C (Index 3)
        existing_topics = sheet.col_values(3)
        
        # Simple text matching (lowercased to catch variations)
        topic_lower = topic.lower().strip()
        for existing in existing_topics:
            if topic_lower in existing.lower().strip():
                print(f"🛑 DUPLICATE DETECTED: '{topic}' has already been made.")
                return True
                
        return False
    except Exception as e:
        print(f"⚠️ Error checking duplicates: {e}")
        return False

def log_completed_video(niche, topic, filename):
    """
    Writes a permanent record of the successful video into the Google Sheet.
    """
    sheet = get_google_sheet()
    if not sheet:
        return False
        
    try:
        # Get current time in USA Eastern Time (adjust timezone as needed)
        eastern = pytz.timezone('US/Eastern')
        current_time = datetime.now(eastern).strftime("%Y-%m-%d %H:%M:%S")
        
        # Append a new row: [Date, Niche, Topic, Filename, Status]
        row_data = [current_time, niche.upper(), topic, filename, "RENDERED"]
        sheet.append_row(row_data)
        
        print(f"✅ Successfully logged '{topic}' to Google Sheets.")
        return True
    except Exception as e:
        print(f"❌ Failed to write to Google Sheets: {e}")
        return False

if __name__ == "__main__":
    # Local testing
    print("Testing Logger Connection...")
    sheet = get_google_sheet()
    if sheet:
        print("Connection Successful!")
