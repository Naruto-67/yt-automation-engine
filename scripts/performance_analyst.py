# scripts/performance_analyst.py
# ═══════════════════════════════════════════════════════════════════════════════
# FIX #6 — lessons_learned / channel_intelligence schema validation + size cap
#
# BUG: performance_analyst.py blindly appended whatever the AI returned to the
# emphasize/avoid arrays and wrote it to the DB (and previously to
# lessons_learned.json). If the AI hallucinated extra keys, returned malformed
# JSON, or wrote a 500-word "rule", the next pipeline run would crash when
# generate_script.py tried to inject the strategy — a silent self-corruption.
#
# FIX: Four layers of defence added around the AI output:
#   1. JSON extraction regex — strips markdown fences, finds the first {...}.
#   2. Key validation — only extracts new_emphasize / new_avoid, ignores extra.
#   3. Content validation — rules must be strings, non-empty, < 300 chars.
#      Malformed rules are skipped with a warning, not crashing the whole run.
#   4. Hard cap at 5 items per list — old code already capped at [-5:] but
#      now the cap is enforced BEFORE writing, not after, preventing bloat
#      if multiple analysts ran concurrently.
#
# FIX #8 (PARTIAL) — Kill switch Python-level guard added here.
# ═══════════════════════════════════════════════════════════════════════════════

import os
import json
import yaml
import re
import sys
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_daily_pulse
from engine.config_manager import config_manager
from engine.logger import logger
from engine.database import db


# ── Kill switch (Fix #8 defence-in-depth) ────────────────────────────────────
_ENABLED = os.environ.get("GHOST_ENGINE_ENABLED", "true").strip().lower()
if _ENABLED == "false":
    print("🔴 [KILL SWITCH] GHOST_ENGINE_ENABLED=false. Analyst halted.")
    sys.exit(0)


MAX_RULES         = 5     # Hard cap on emphasize / avoid lists
MAX_RULE_CHARS    = 300   # Rules longer than this are likely AI hallucinations


def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extract_rules_safely(raw_text: str) -> tuple:
    """
    Safely extract (new_emphasize, new_avoid) from the AI's raw response.

    Returns (emphasize_str_or_None, avoid_str_or_None).
    Never raises — any parse failure returns (None, None) so the rest of the
    analysis run continues normally without writing bad data.
    """
    if not raw_text:
        return None, None

    # Step 1: Strip markdown fences and find the first JSON object
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()
    match   = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        logger.error(f"[ANALYST] AI response contained no JSON object: {raw_text[:200]}")
        return None, None

    # Step 2: Parse the JSON
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.error(f"[ANALYST] JSON parse failed: {e}. Raw: {match.group(0)[:200]}")
        return None, None

    # Step 3: Extract and validate each rule
    new_emphasize = parsed.get("new_emphasize")
    new_avoid     = parsed.get("new_avoid")

    def _validate_rule(rule, key_name):
        if rule is None:
            return None
        if not isinstance(rule, str):
            logger.engine(f"⚠️ [ANALYST] '{key_name}' is not a string (got {type(rule).__name__}). Skipping.")
            return None
        rule = rule.strip()
        if not rule:
            logger.engine(f"⚠️ [ANALYST] '{key_name}' is empty. Skipping.")
            return None
        if len(rule) > MAX_RULE_CHARS:
            # Truncate with a warning — don't discard entirely, just trim
            logger.engine(
                f"⚠️ [ANALYST] '{key_name}' too long ({len(rule)} chars). Truncating to {MAX_RULE_CHARS}."
            )
            rule = rule[:MAX_RULE_CHARS].rsplit(" ", 1)[0]  # Trim at word boundary
        return rule

    return _validate_rule(new_emphasize, "new_emphasize"), _validate_rule(new_avoid, "new_avoid")


def _cap_list(lst: list) -> list:
    """Keep only the most recent MAX_RULES entries."""
    return lst[-MAX_RULES:] if len(lst) > MAX_RULES else lst


def run_daily_analysis():
    logger.engine("📊 Initiating Performance Audit...")
    prompts_cfg = load_config_prompts()

    for channel in config_manager.get_active_channels():
        youtube = get_youtube_client(channel.youtube_refresh_token_env)
        if not youtube:
            continue

        intel = db.get_channel_intelligence(channel.channel_id)

        try:
            res   = youtube.channels().list(part="statistics", mine=True).execute()
            stats = res["items"][0]["statistics"]
            views = int(stats.get("viewCount", 0))
            subs  = int(stats.get("subscriberCount", 0))

            sys_msg  = prompts_cfg["analyst"]["system_prompt"]
            user_msg = prompts_cfg["analyst"]["user_template"].format(
                views=views,
                subs=subs,
                current_strategy=intel["emphasize"][-2:],
            )

            raw_analysis, _ = quota_manager.generate_text(
                user_msg, task_type="analysis", system_prompt=sys_msg
            )

            if raw_analysis:
                # ── FIX #6: Validated extraction instead of blind JSON parse ─
                new_emphasize, new_avoid = _extract_rules_safely(raw_analysis)

                if new_emphasize:
                    intel["emphasize"].append(new_emphasize)
                    logger.success(f"[ANALYST] New emphasize rule: {new_emphasize[:80]}...")
                else:
                    logger.engine("⚠️ [ANALYST] No valid emphasize rule extracted — skipping update.")

                if new_avoid:
                    intel["avoid"].append(new_avoid)
                    logger.success(f"[ANALYST] New avoid rule: {new_avoid[:80]}...")
                else:
                    logger.engine("⚠️ [ANALYST] No valid avoid rule extracted — skipping update.")

                # Hard cap BEFORE writing to DB
                intel["emphasize"] = _cap_list(intel["emphasize"])
                intel["avoid"]     = _cap_list(intel["avoid"])
                # ─────────────────────────────────────────────────────────────

            # Write validated data — even if AI failed, this persists existing data
            db.upsert_channel_intelligence(
                channel.channel_id,
                intel["emphasize"],
                intel["avoid"],
                intel["recent_tags"],
                intel["preferred_visuals"],
            )

            notify_daily_pulse(
                views, subs,
                {"emphasize": [intel["emphasize"][-1]] if intel["emphasize"] else [],
                 "avoid":     [intel["avoid"][-1]]     if intel["avoid"]     else []},
            )
            logger.success(f"Strategy updated for {channel.channel_name}")

        except Exception as e:
            logger.error(f"[ANALYST] Analysis failed for {channel.channel_name}: {e}")


if __name__ == "__main__":
    run_daily_analysis()
