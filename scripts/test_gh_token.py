# scripts/test_gh_token.py — Test GitHub Token API status & endpoints
import os
import sys
import urllib.request
import json

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

token = os.environ.get("GH_MODELS_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip() or os.environ.get("GITHUB_TOKEN", "").strip()

print("========================================================================================")
print("🔑 TESTING GITHUB TOKEN ACCESS & ENDPOINTS")
print("========================================================================================")

if not token:
    print("❌ Token is NOT set in environment.")
    sys.exit(0)

# Mask token for secrecy
masked = token[:3] + "..." + token[-3:] if len(token) > 6 else "***"
print(f"🔑 Token Present: {masked}")

# 1. Standard GitHub User API check
try:
    req = urllib.request.Request("https://api.github.com/user", headers={"Authorization": f"Bearer {token}", "User-Agent": "Python"})
    res = urllib.request.urlopen(req)
    data = json.loads(res.read().decode('utf-8'))
    print(f"✅ GitHub User API Authentication: SUCCESS (User: {data.get('login')})")
except Exception as e:
    print(f"⚠️ GitHub User API Check: {e}")

# 2. Azure AI Inference Endpoint check (Legacy endpoint)
azure_endpoint = "https://models.inference.ai.azure.com/chat/completions"
candidates = ["gpt-4o-mini", "meta-llama-3.3-70b-instruct", "Phi-3.5-mini-instruct", "Mistral-large-2407"]

print("\n🔬 Testing Azure AI Inference Endpoint (https://models.inference.ai.azure.com/chat/completions):")
for model in candidates:
    try:
        payload = json.dumps({"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 2}).encode('utf-8')
        req = urllib.request.Request(
            azure_endpoint,
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "Ghost-Engine/2.0"}
        )
        res = urllib.request.urlopen(req)
        body = res.read().decode('utf-8', errors='ignore').strip()
        c_type = res.headers.get("content-type", "").lower()
        if "application/json" in c_type:
            print(f"   ✅ Model [{model}]: PASS (HTTP 200 JSON)")
        else:
            print(f"   ⚠️ Model [{model}]: HTTP 200 returned non-JSON: '{body[:30]}' (Decommissioned)")
    except urllib.error.HTTPError as he:
        err_body = he.read().decode('utf-8', errors='ignore')[:150]
        print(f"   ❌ Model [{model}]: HTTP {he.code} -> {err_body}")
    except Exception as e:
        print(f"   ❌ Model [{model}]: FAIL -> {e} (Decommissioned DNS)")

# 3. GitHub Models Inference Endpoint check
gh_endpoint = "https://models.github.ai/inference/chat/completions"
print("\n🔬 Testing GitHub Models Inference Endpoint (https://models.github.ai/inference/chat/completions):")
for model in candidates:
    try:
        payload = json.dumps({"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 2}).encode('utf-8')
        req = urllib.request.Request(
            gh_endpoint,
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "Ghost-Engine/2.0"}
        )
        res = urllib.request.urlopen(req)
        body = res.read().decode('utf-8', errors='ignore').strip()
        c_type = res.headers.get("content-type", "").lower()
        if "application/json" in c_type:
            data = json.loads(body)
            print(f"   ✅ Model [{model}]: PASS (HTTP 200 JSON)")
        else:
            print(f"   ⚠️ Model [{model}]: HTTP 200 returned non-JSON text '{body[:30]}' (Service retired as of July 2026)")
    except urllib.error.HTTPError as he:
        err_body = he.read().decode('utf-8', errors='ignore')[:150]
        print(f"   ❌ Model [{model}]: HTTP {he.code} -> {err_body}")
    except Exception as e:
        print(f"   ❌ Model [{model}]: FAIL -> {e}")

print("========================================================================================")
