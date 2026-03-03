import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

def get_sheet(tab_name):
    """Authenticates the bot and connects to the specified tab."""
    scope = [
        "https://spreadsheets.google.com/feeds", 
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds_json = os.environ.get("GCP_CREDENTIALS_JSON")
    if not creds_json:
        print("Error: GCP_CREDENTIALS_JSON is missing from secrets.")
        return None
        
    try:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        sheet_id = os.environ.get("GOOGLE_SHEETS_ID")
        return client.open_by_key(sheet_id).worksheet(tab_name)
    except Exception as e:
        print(f"Authentication failed: {e}")
        return None

def log_action(tab_name, data_list):
    """Appends a row of data to the specified tab with a timestamp."""
    try:
        sheet = get_sheet(tab_name)
        if sheet:
            # Generate a standard timestamp
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            
            # Combine timestamp with your data
            row_to_insert = [timestamp] + data_list
            
            # Write it to the next empty row
            sheet.append_row(row_to_insert)
            print(f"Successfully logged data to the '{tab_name}' tab.")
    except Exception as e:
        print(f"Failed to write to Google Sheets: {e}")

if __name__ == "__main__":
    # Test message to ensure the bot can write to the sheet
    log_action("daily_health", ["System Check", "Logger is online and connected to the database!"])
