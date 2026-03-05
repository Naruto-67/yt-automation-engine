import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz

def get_google_sheet():
    creds_json = os.environ.get("GCP_CREDENTIALS_JSON")
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID")
    if not creds_json or not sheet_id: return None
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        return gspread.authorize(creds).open_by_key(sheet_id).sheet1
    except: return None

def is_script_duplicate(hook):
    sheet = get_google_sheet()
    if not sheet: return False
    try:
        hooks = sheet.col_values(3)
        return any(hook.lower().strip() in h.lower() for h in hooks)
    except: return False

def log_completed_video(niche, hook, filename):
    sheet = get_google_sheet()
    if not sheet: return
    try:
        ist = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%Y-%m-%d %H:%M")
        sheet.append_row([ist, niche.upper(), hook, filename, "VAULTED"])
    except: pass
