ghost-engine-v5.0-titan
INTERNAL AUTOMATION SYSTEM — DO NOT REDISTRIBUTE
State-Persistent, Multi-Tenant Enterprise Automation Platform.

🏗️ Architectural Overview
Ghost Engine V5.0 is an event-driven, idempotent content production system. Unlike linear scripts, V5.0 utilizes a centralized SQLite state machine and Context-Switching Orchestration to manage an unlimited number of YouTube channels simultaneously from a single repository.

Core Philosophy:
Idempotency: Every stage (Script → Voice → Visuals → Render) checks the SQLite database before execution. If a GitHub Runner crashes, the system resumes mid-cycle with zero duplicate API spend.

Multi-Tenancy: The system uses "Amnesia Walls" to isolate channel identities. Each channel has its own niche, performance strategy, and Discord notification routing.

Autonomous Survival: Features self-healing "Safe Mode," 80/20 Explore/Exploit research logic, and auto-discovery for AI models (Gemini/Groq/HuggingFace) to survive provider deprecations.

📂 Repository Map (LLM Context Anchor)
Plaintext
naruto-67-yt-automation-engine/
├── main.py                     # Entry point & Kill-Switch handler.
├── config/
│   ├── channels.yaml           # Source of Truth: Channel IDs, Niches, & Webhook mapping.
│   ├── prompts.yaml            # Master Prompt Registry (80/20 Research & AI Director).
│   ├── settings.yaml           # API Limits, Guardian costs, and Subtitle styling.
│   └── providers.yaml          # Dynamic failover chains (Gemini → Groq).
├── engine/
│   ├── database.py             # SQLite CRUD layer (The sole Source of Truth).
│   ├── models.py               # Pydantic strictly-typed data schemas.
│   ├── orchestrator.py         # Context Switcher: Identity Sync & Multi-channel dispatcher.
│   ├── job_runner.py           # The State Machine: Idempotent execution core.
│   ├── guardian.py             # Resource forecaster & Multi-tenant Safe Mode manager.
│   └── logger.py               # Structured [TAG] logging system.
├── scripts/
│   ├── dynamic_researcher.py   # Trend scraper with 80/20 Explore/Exploit logic.
│   ├── performance_analyst.py  # YouTube Analytics → SQLite Strategy loop.
│   ├── generate_script.py      # AI Director (Scripting + Voice/Color selection).
│   ├── generate_visuals.py     # 4-Tier Image Cascade (Cloudflare → HF → Pexels → Grad).
│   ├── generate_voice.py       # TTS Pipeline (Kokoro → Groq Orpheus).
│   ├── render_video.py         # FFmpeg Master (1080x1920, 30fps, 59s Cap).
│   ├── youtube_manager.py      # OAuth Vaulting & Identity Sync.
│   ├── niche_discovery.py      # AI-driven niche repair for blank channels.
│   └── discord_notifier.py     # Scoped webhook dispatcher (Mission Control).
└── memory/
    └── ghost_engine.db         # Persistent state (Must be committed back to repo).
🛠️ API Acquisition Guide (Baby Steps)
1. Google Gemini API (The Brain)
Go to Google AI Studio.

Log in with your Google Account.

Click "Get API key" on the left sidebar.

Copy the key and add it to GitHub Secrets as GEMINI_API_KEY.

2. Groq Cloud (The Fallback & Fast TTS)
Go to Groq Console.

Under "API Keys", click "Create API Key".

Copy the key and add it to GitHub Secrets as GROQ_API_KEY.

3. YouTube API & OAuth Tokens (The Connection)
Note: This allows the AI to upload, create playlists, and read analytics.

Project Setup: Go to Google Cloud Console, create a project, and enable the YouTube Data API v3.

Consent Screen: Go to "APIs & Services" > "OAuth consent screen". Set User Type to External. Add your email as a Test User.

Scopes: Add these 4 scopes: .../auth/youtube.upload, .../auth/youtube, .../auth/youtube.force-ssl, and .../auth/youtubepartner.

Credentials: Create "OAuth client ID" as a Web Application.

Add Redirect URI: https://developers.google.com/oauthplayground

Copy Client ID and Client Secret to GitHub Secrets.

Get Refresh Token (Manual):

Go to OAuth 2.0 Playground.

Click Settings (cog) > Check "Use your own OAuth credentials". Paste ID and Secret.

Select the YouTube scopes on the left and click Authorize APIs.

Click Exchange authorization code for tokens.

Copy the Refresh Token into GitHub Secrets as YOUTUBE_REFRESH_TOKEN.

4. Cloudflare AI (The Visuals)
Log into your Cloudflare Dashboard.

Go to "AI" on the sidebar. Copy your Account ID. Add as CF_ACCOUNT_ID.

Go to "My Profile" > "API Tokens". Create a token with "Workers AI (Read)" permissions. Add as CF_API_TOKEN.

📈 System Operation & Schedules (UTC)
Workflow	UTC Time	Purpose
01_daily_pipeline	00:00	Produce: script → voice → visuals → render → vault.
02_daily_publisher	06:00	Publish: Move from vault to AI-timed public release.
03_daily_pulse	17:30	Analyze: Fetch stats & update SQLite strategy rules.
05_weekly_research	20:00 Sun	Research: Refill queue using 80/20 Explore/Exploit.
🧠 Mission Control (Discord)
The system routes telemetry to different Discord channels based on the active YouTube channel.

🪬 Production Success: Detailed report on AI logic, size, and duration.

🚨 Critical Crash: Direct alert for auth failures or code breaks.

⚙️ Provider Swap: Notification when Gemini fails and Groq takes over.

⚡ Quota Warning: Alerts when API usage hits 80% (Point 19).

🛡️ Safe Mode: Notification when the Guardian bypasses AI imagery to save credits.

🛡️ Error Handling & Self-Healing
Multi-Tier Visuals: Cloudflare → HuggingFace → Pexels → Local Gradient.

Proportional Fallback: If Whisper transcription fails, captions are mathematically distributed.

Identity Sync: If you change your YouTube channel name, the system automatically detects it, updates channels.yaml, and pushes the change back to the repository.

Niche Discovery: If a channel is added without a niche, the AI analyzes previous uploads to "self-configure" its own niche.

Internal use only. No external documentation, marketing, or contribution guidelines.
