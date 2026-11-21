"""All Gemini model IDs live here, so we only ever change them in one place."""

# Decisions API: calibrated yes/no, choice, and score answers (score tells, pick the lie, route, gate)
DECISION_MODEL = "gemini-decision-1"

# Transcription with word-level timestamps (feeds delay, fillers, and tell times)
TRANSCRIBE_MODEL = "gemini-3.5-transcribe"

# Fast, low-cost tier: transcription, splitting statements, host table talk
HYDROGEN_MODEL = "gemini-4-hydrogen"

# Agentic video: timestamped observations and the follow-up question
NEON_MODEL = "gemini-4-neon"

# Deep reasoning tier (stretch: Tell Reports)
CARBON_MODEL = "gemini-4-carbon"

# Stretch goals only
EVAL_AGENT_MODEL = "antigravity-preview-09-2026"
BUSTED_CLIP_MODEL = "gemini-omni-1.2-flash"
LIVE_MODEL = "gemini-3.8-live"
