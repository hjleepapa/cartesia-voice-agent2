# Cartesia Voice Agent (Convonet-Style Scaffold)

Open-source-friendly scaffold for a **Cartesia STT/TTS + Anthropic Claude + Notion MCP** voice agent that follows the **Convonet-style** planner → executor → critic loop. This repo is designed for hackathon iteration: minimal but functional, with clear extension points.

## What This Implements
- **Cartesia STT (Batch)** using `https://api.cartesia.ai/stt` (no Whisper).
- **Cartesia TTS** using the official Python SDK.
- **Claude** tool-calling loop (Anthropic) for planning + execution.
- **Notion MCP + Custom Agent** tool integration (optional).
- **Memory store** (SQLite) for short-term + long-term context.

## Quick Start
1. Create a virtual environment and install deps:
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -e .`
2. Copy env template:
   - `cp .env.example .env`
3. Fill in API keys and Notion MCP settings.
4. Run a basic turn:
   - `voice-agent --audio ./samples/input.wav --output ./samples/response.wav`
   - or `voice-agent --text "Search and find the best mortgage program based on my credit score and income" --output ./samples/response.wav`

## Demo Server (WebRTC/Voice Assistant UI)
Start the demo server and open the WebRTC UI entry point:

- `voice-agent-server`
- Open: `http://localhost:8000/webrtc/voice-assistant`

This serves the Convonet call center UI and exposes stubbed `/call-center/api/*` endpoints,
plus a demo voice agent endpoint at `/call-center/api/assistant/respond`.

## Notion MCP and Custom Agent
This scaffold uses an MCP client over stdio. Configure the MCP server command and args:

```
NOTION_MCP_COMMAND=npx
NOTION_MCP_ARGS=["@notionhq/notion-mcp-server"]
NOTION_CUSTOM_AGENT_TOOL=notion.customAgent.run
```

If your Notion MCP server uses a different command, update these values. The tool name is configurable so you can bind to your Custom Agent workflow.

## Architecture (Convonet-Style)
- **Planner**: decomposes the task and decides which tools to use.
- **Executor**: performs tool calls (Notion MCP, search, etc).
- **Critic**: checks and refines the final answer.
- **Memory**: stores preferences and per-session summaries.

## Directory Layout
```
cartesia_voice_agent/
  src/voice_agent/
    agents.py
    cli.py
    config.py
    llm_claude.py
    mcp_notion.py
    memory.py
    stt_cartesia.py
    tools.py
    tts_cartesia.py
```

## Notes
- This is intentionally lightweight and open-source-friendly.
- Swap in local models or alternative tools by implementing new tool adapters.
- Mortgage prompts are copied into this project at
  `cartesia_voice_agent/src/voice_agent/convonet_mortgage_prompts.py` to avoid
  relying on external folders.
