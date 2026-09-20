# scratch/poll_github_runs.py — Automated GitHub Actions Run Monitor
import sys
import urllib.request
import json
import time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

RUN_IDS = [35496589579, 35496589527]

print("⏳ [GITHUB ACTIONS MONITOR] Waiting for cloud runs to complete...")
start_time = time.time()

completed = {}

while len(completed) < len(RUN_IDS):
    if time.time() - start_time > 300: # 5 min safety ceiling
        print("⚠️ Monitoring ceiling reached.")
        break
    
    for run_id in RUN_IDS:
        if run_id in completed:
            continue
        try:
            url = f"https://api.github.com/repos/Naruto-67/yt-automation-engine/actions/runs/{run_id}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Python'})
            res = urllib.request.urlopen(req)
            data = json.loads(res.read().decode('utf-8'))
            
            status = data.get('status')
            conclusion = data.get('conclusion')
            name = data.get('name')
            
            print(f"   ► Run {run_id} ({name}): status='{status}', conclusion='{conclusion}'")
            if status == 'completed':
                completed[run_id] = data
        except Exception as e:
            print(f"   ⚠️ Error checking run {run_id}: {e}")
    
    if len(completed) < len(RUN_IDS):
        time.sleep(10)

print("\n🎉 [FINAL SUMMARY] All GitHub Actions Cloud Runs Completed!")
for rid, info in completed.items():
    icon = "✅" if info.get('conclusion') == 'success' else "❌"
    print(f"{icon} {info.get('name')} | Status: {info.get('conclusion').upper()} | URL: {info.get('html_url')}")
