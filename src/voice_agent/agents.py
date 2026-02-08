from typing import Any, Dict, List

from .convonet_mortgage_prompts import MORTGAGE_SYSTEM_PROMPT

from .llm_claude import ClaudeClient
from .memory import MemoryStore
from .tools import TOOL_DEFS, ToolRegistry



PLANNER_PROMPT = "Create a brief plan and note needed tools. Plain text."

CRITIC_PROMPT = "Rewrite if needed. Return only the final response. Keep it short and spoken."


class MortgageAgent:
    def __init__(self, memory: MemoryStore, tool_log: List[Dict[str, Any]] | None = None) -> None:
        self.memory = memory
        self.tools = ToolRegistry(memory=self.memory, tool_log=tool_log)
        self.llm = ClaudeClient()

    async def _handle_tool(self, name: str, payload: Dict[str, Any]) -> str:
        if name == "search_web":
            result = await self.tools.search_web(payload["query"])
            return result.content
        if name == "save_memory":
            result = await self.tools.save_memory(payload["role"], payload["content"])
            return result.content
        if name == "recall_memory":
            limit = payload.get("limit", 6)
            result = await self.tools.recall_memory(limit=limit)
            return result.content
        if name == "upsert_mortgage_application":
            result = await self.tools.upsert_mortgage_application(
                full_name=payload["full_name"],
                date_of_birth=payload["date_of_birth"],
                credit_score=payload["credit_score"],
                monthly_income=payload["monthly_income"],
                down_payment_amount=payload["down_payment_amount"],
                property_value=payload["property_value"],
            )
            return result.content
        if name == "transfer_to_human":
            result = await self.tools.transfer_to_human(
                reason=payload.get("reason", "User requested transfer to a human agent"),
                extension=payload.get("extension"),
            )
            return result.content
        return f"Unknown tool: {name}"

    async def run(self, user_text: str) -> str:
        self.memory.add(role="user", content=user_text)
        memory_context = self.memory.recent(limit=4)
        memory_lines = "\n".join([f"{role}: {content}" for role, content in memory_context])

        planner_input = [
            {"role": "user", "content": f"User: {user_text}\nMemory:\n{memory_lines}"}
        ]
        plan, _ = await self.llm.run_with_tools(
            system_prompt=PLANNER_PROMPT,
            messages=planner_input,
            tools=[],
            tool_handler=self._handle_tool,
            max_loops=1,
        )

        execution_messages: List[Dict[str, Any]] = [
            {
                "role": "user",
                "content": f"User request: {user_text}\nPlan: {plan}\nMemory: {memory_lines}",
            }
        ]
        draft, _ = await self.llm.run_with_tools(
            system_prompt=MORTGAGE_SYSTEM_PROMPT,
            messages=execution_messages,
            tools=TOOL_DEFS,
            tool_handler=self._handle_tool,
            max_loops=4,
        )

        critic_input = [
            {
                "role": "user",
                "content": f"Draft response:\n{draft}\nUser request: {user_text}",
            }
        ]
        final, _ = await self.llm.run_with_tools(
            system_prompt=CRITIC_PROMPT,
            messages=critic_input,
            tools=[],
            tool_handler=self._handle_tool,
            max_loops=1,
        )
        self.memory.add(role="assistant", content=final)
        return final
