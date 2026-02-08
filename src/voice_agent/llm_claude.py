from typing import Any, Dict, List, Optional, Tuple

from anthropic import AsyncAnthropic

from .config import settings


class ClaudeClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or settings.anthropic_api_key
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude")
        self.model = model or settings.anthropic_model
        self.client = AsyncAnthropic(api_key=self.api_key)

    async def run_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_handler,
        max_loops: int = 3,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        loop_count = 0
        while loop_count < max_loops:
            response = await self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=400,
                temperature=0.2,
            )
            if response.stop_reason != "tool_use":
                text_blocks = [
                    block.text for block in response.content
                    if getattr(block, "type", None) == "text" and getattr(block, "text", None)
                ]
                if text_blocks:
                    return text_blocks[0], messages
                # Fallback when Claude returns no text blocks
                return "One moment, please.", messages

            tool_uses = [block for block in response.content if block.type == "tool_use"]
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tool_use in tool_uses:
                tool_output = await tool_handler(tool_use.name, tool_use.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": tool_output,
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            loop_count += 1

        return "I reached the tool execution limit. Please try again.", messages
