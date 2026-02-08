import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv


load_dotenv()


def _parse_json_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    # Fallback: split on spaces
    return [item for item in value.split(" ") if item]


@dataclass
class Settings:
    anthropic_api_key: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

    cartesia_api_key: Optional[str] = os.getenv("CARTESIA_API_KEY")
    cartesia_version: str = os.getenv("CARTESIA_VERSION", "2025-04-16")
    cartesia_stt_model: str = os.getenv("CARTESIA_STT_MODEL", "ink-whisper")
    cartesia_tts_model: str = os.getenv("CARTESIA_TTS_MODEL", "sonic-3")
    cartesia_voice_id: Optional[str] = os.getenv("CARTESIA_VOICE_ID")
    cartesia_tts_speed: Optional[float] = (
        float(os.getenv("CARTESIA_TTS_SPEED"))
        if os.getenv("CARTESIA_TTS_SPEED")
        else 0.88
    )
    cartesia_tts_volume: Optional[float] = (
        float(os.getenv("CARTESIA_TTS_VOLUME"))
        if os.getenv("CARTESIA_TTS_VOLUME")
        else 0.85
    )
    cartesia_tts_emotion: Optional[str] = os.getenv("CARTESIA_TTS_EMOTION", "calm")

    memory_db_uri: str = (
        os.getenv("MEMORY_DB_URI")
        or os.getenv("DB_URI")
        or os.getenv("MEMORY_DB_PATH", "sqlite:///data/memory.sqlite")
    )

    # Notion MCP + Custom Agent
    notion_mcp_command: Optional[str] = os.getenv("NOTION_MCP_COMMAND")
    notion_mcp_args: List[str] = field(
        default_factory=lambda: _parse_json_list(os.getenv("NOTION_MCP_ARGS"))
    )
    notion_custom_agent_tool: Optional[str] = os.getenv("NOTION_CUSTOM_AGENT_TOOL")

    # Web search (optional)
    exa_api_key: Optional[str] = os.getenv("EXA_API_KEY")


settings = Settings()
