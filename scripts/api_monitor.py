# scripts/api_monitor.py — Ghost Engine V14.0
import os
import requests
from datetime import datetime
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary, notify_error, set_channel_context
from engine.config_manager import config_manager

class APIMonitor:
    def __init__(self):
        self.providers = {
            "Google Gemini": "https://ai.google.dev/gemini-api/docs/changelog",
            "YouTube Data API": "https://developers.google.com/youtube/v3/revision_history",
            "Groq Cloud": "https://console.groq.com/docs/models",
            "Cloudflare Workers AI": "https://developers.cloudflare.com/workers-ai/models/"
        }

    def run_audit(self):
        print("🕵️ [MONITOR] Initiating Weekly Technical Audit...")
        
        # GOD-TIER FIX: Inject Discord context so standalone audits can dispatch webhooks
        active_channels = config_manager.get_active_channels()
        if active_channels:
            set_channel_context(active_channels[0])
            
        findings = []

        audit_prompt = f"""
        Today is {datetime.now().strftime('%Y-%m-%d')}. 
        Perform a technical search for the following providers and check for any 
        DEPRECATION notices, NEW MODEL releases (like Gemini 3.0 or Llama 5), 
        or QUOTA changes scheduled for 2026:
        {list(self.providers.keys())}
        
        Focus on:
        1. Models being shut down in the next 30 days.
        2. New 'Flash' or 'Lite' models that are cheaper/faster.
        3. Any changes to the YouTube 10,000 unit daily quota.
        
        Format your response as a concise list of ACTIONABLE items for a lead developer.
        If no changes found, simply say 'No critical updates detected.'
        """

        try:
            report, _ = quota_manager.generate_text(audit_prompt, task_type="analysis")
            
            if "No critical updates" in report:
                print("✅ [MONITOR] Stack is stable. No action required.")
                return

            msg = f"🛡️ **Weekly Stack Audit Result**\n\n{report}"
            notify_summary(True, msg)
            print("📡 [MONITOR] Audit report dispatched to Discord.")

        except Exception as e:
            notify_error("API Monitor", "Audit Failure", str(e))

if __name__ == "__main__":
    monitor = APIMonitor()
    monitor.run_audit()
