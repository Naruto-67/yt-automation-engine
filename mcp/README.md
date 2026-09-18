# Ghost Engine Model Context Protocol (MCP) Server

The **Ghost Engine MCP Server** exposes the YouTube Shorts automation pipeline, script intelligence, slideshow risk auditing, fact verification, and system health checks to external AI agent systems like **Antigravity**, **Claude Desktop**, **Cursor**, and **Windsurf**.

---

## 🛠️ Exposed Tools

| Tool | Description |
| :--- | :--- |
| `preview_script` | Simulates and validates script generation against the 7 retention quality gates (85-125 words, circular loop, living characters). |
| `audit_slideshow_risk` | Audits candidate visual scene prompts across 6 OpenMontage dimensions and returns auto-remedy instructions. |
| `verify_topic_facts` | Grounds factual topics with real-time web grounding and extracts empirical anchors. |
| `inspect_decision_log` | Queries the CHAI append-only architectural ledger (`memory/decision_log.jsonl`). |
| `get_channel_intelligence` | Returns channel configuration, brand voice, creative lenses, and golden exemplars. |
| `inspect_system_health` | Runs pre-flight health audit on configs, API keys, disk space, and runtime availability. |

---

## 📚 Exposed Resources

- `channel://config`: Multi-channel configuration details from `config/channels.yaml`.
- `memory://golden_trajectories`: High-performing historical script exemplars from `memory/success_patterns.json`.

---

## 🔌 Setup Guide

### 1. Claude Desktop
Add the following entry to your `claude_desktop_config.json` (`%APPDATA%\Claude\claude_desktop_config.json` on Windows or `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "ghost-engine": {
      "command": "python",
      "args": [
        "d:/Github/yt-automation-engine-main/mcp/ghost_engine_server.py"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### 2. Antigravity & Cursor
In Cursor MCP Settings or Antigravity MCP configuration:
- **Type**: `stdio`
- **Command**: `python`
- **Arguments**: `mcp/ghost_engine_server.py`

