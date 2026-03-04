import time
import functools
import traceback

class QuotaManager:
    """
    This is the Central Controller. 
    Instead of every script panicking when Google says 'Too Busy', 
    they will all come here to wait in line.
    """
    def __init__(self, max_retries=5, initial_wait=35):
        self.max_retries = max_retries
        self.initial_wait = initial_wait

    def safe_execute(self, func, *args, **kwargs):
        """
        This function wraps your Gemini calls.
        If it sees a '429' error, it pauses the whole script.
        """
        retries = 0
        wait_time = self.initial_wait

        while retries < self.max_retries:
            try:
                # Try to run the actual Gemini command
                return func(*args, **kwargs)

            except Exception as e:
                error_msg = str(e).lower()
                
                # If the error is about Quota (429) or being Exhausted
                if "429" in error_msg or "resource_exhausted" in error_msg:
                    print(f"\n[QUOTA MANAGER] 🛑 Quota hit! (15 requests per minute limit reached)")
                    print(f"[QUOTA MANAGER] ⏳ Pausing entire workflow for {wait_time} seconds...")
                    
                    time.sleep(wait_time)
                    
                    retries += 1
                    # If it fails again, we wait even longer (Exponential Backoff)
                    wait_time *= 2 
                    print(f"[QUOTA MANAGER] 🔄 Resuming now. Attempt {retries}/{self.max_retries}...")
                    continue
                
                # If it's a 500 error (Google's servers are glitching)
                elif "500" in error_msg or "503" in error_msg:
                    print(f"[QUOTA MANAGER] ⚠️ Google Server is hiccuping. Waiting 10s...")
                    time.sleep(10)
                    retries += 1
                    continue

                # If it's a real error (like a typo in code), stop immediately so we can fix it
                else:
                    print(f"[QUOTA MANAGER] ❌ Specific Error: {e}")
                    raise e

        print("🚨 [QUOTA MANAGER] Fatal: Could not recover from Quota limits.")
        return None

# We create one instance here so all other files can share it
quota_manager = QuotaManager()
