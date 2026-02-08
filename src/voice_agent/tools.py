from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import os

import httpx

from .config import settings
from .memory import MemoryStore
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uuid import uuid4
import re


@dataclass
class ToolResult:
    content: str


class ToolRegistry:
    def __init__(self, memory: MemoryStore, tool_log: List[Dict[str, Any]] | None = None) -> None:
        self.memory = memory
        self.tool_log = tool_log
        self._db_engine = None
        self._db_sessionmaker = None

    def _get_db_session(self):
        if self._db_sessionmaker is None:
            db_uri = settings.memory_db_uri
            if not db_uri:
                raise RuntimeError("DB_URI is required for mortgage tools.")
            self._db_engine = create_engine(db_uri, pool_pre_ping=True)
            self._db_sessionmaker = sessionmaker(bind=self._db_engine)
            try:
                from convonet.models.base import Base
                from convonet.models import mortgage_models  # noqa: F401
                from convonet.models import user_models  # noqa: F401
                Base.metadata.create_all(bind=self._db_engine)
            except Exception:
                pass
        return self._db_sessionmaker()

    def _get_demo_user_id(self, full_name: str) -> str:
        from convonet.models.user_models import User

        db = self._get_db_session()
        try:
            existing = db.query(User).filter(User.email == "demo@convonet.local").first()
            if existing:
                return str(existing.id)
            name_parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
            first_name = name_parts[0] if name_parts else "Demo"
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "User"
            user = User(
                email="demo@convonet.local",
                username="demo-mortgage",
                password_hash=str(uuid4()),
                first_name=first_name,
                last_name=last_name,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return str(user.id)
        finally:
            db.close()

    async def search_web(self, query: str) -> ToolResult:
        if not settings.exa_api_key:
            return ToolResult(
                content="Web search is not configured. Set EXA_API_KEY to enable it."
            )
        payload = {"query": query, "num_results": 5}
        headers = {"x-api-key": settings.exa_api_key}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.exa.ai/search",
                json=payload,
                headers=headers,
            )
        response.raise_for_status()
        data = response.json()
        result = ToolResult(content=str(data))
        results_list: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            for item in data.get("results", []):
                results_list.append(
                    {
                        "title": item.get("title"),
                        "url": item.get("url"),
                        "snippet": item.get("snippet") or item.get("highlights", ""),
                        "source": item.get("source"),
                    }
                )
        if self.tool_log is not None:
            self.tool_log.append(
                {
                    "tool_name": "search_web",
                    "arguments": {"query": query},
                    "result": result.content,
                    "results": results_list,
                }
            )
        return result

    async def save_memory(self, role: str, content: str) -> ToolResult:
        self.memory.add(role=role, content=content)
        result = ToolResult(content="Saved.")
        if self.tool_log is not None:
            self.tool_log.append(
                {
                    "tool_name": "save_memory",
                    "arguments": {"role": role, "content": content},
                    "result": result.content,
                }
            )
        return result

    async def recall_memory(self, limit: int = 6) -> ToolResult:
        items = self.memory.recent(limit=limit)
        serialized = [{"role": role, "content": content} for role, content in items]
        result = ToolResult(content=str(serialized))
        if self.tool_log is not None:
            self.tool_log.append(
                {
                    "tool_name": "recall_memory",
                    "arguments": {"limit": limit},
                    "result": result.content,
                }
            )
        return result

    async def upsert_mortgage_application(
        self,
        full_name: str,
        date_of_birth: str,
        credit_score: int,
        monthly_income: float,
        down_payment_amount: float,
        property_value: float,
    ) -> ToolResult:
        from convonet.models.mortgage_models import MortgageApplication, ApplicationStatus
        from sqlalchemy import desc

        db = self._get_db_session()
        try:
            user_id = self._get_demo_user_id(full_name)
            application = (
                db.query(MortgageApplication)
                .filter(MortgageApplication.user_id == user_id)
                .order_by(desc(MortgageApplication.created_at))
                .first()
            )
            if application is None:
                application = MortgageApplication(
                    user_id=user_id,
                    status=ApplicationStatus.FINANCIAL_REVIEW,
                )
                db.add(application)

            application.credit_score = credit_score
            application.monthly_income = monthly_income
            application.down_payment_amount = down_payment_amount
            application.property_value = property_value
            application.loan_amount = max(property_value - down_payment_amount, 0)
            application.financial_review_completed = True
            application.app_metadata = {
                "full_name": full_name,
                "date_of_birth": date_of_birth,
            }

            db.commit()
            db.refresh(application)

            result = ToolResult(
                content=f"Created or updated mortgage application {application.id}."
            )
            if self.tool_log is not None:
                self.tool_log.append(
                    {
                        "tool_name": "upsert_mortgage_application",
                        "arguments": {
                            "full_name": full_name,
                            "date_of_birth": date_of_birth,
                            "credit_score": credit_score,
                            "monthly_income": monthly_income,
                            "down_payment_amount": down_payment_amount,
                            "property_value": property_value,
                        },
                        "result": result.content,
                    }
                )
            return result
        finally:
            db.close()

    async def transfer_to_human(
        self,
        reason: str = "User requested transfer to a human agent",
        extension: Optional[str] = None,
    ) -> ToolResult:
        target_extension = extension or os.getenv("HUMAN_TRANSFER_EXTENSION", "2001")
        base_url = os.getenv("PUBLIC_BASE_URL") or os.getenv("BASE_URL") or "http://localhost:8000"
        transfer_url = f"{base_url.rstrip('/')}/convonet_todo/twilio/transfer?extension={target_extension}"
        try:
            self.memory.add(
                role="assistant",
                content=f"Transfer requested to extension {target_extension}.",
            )
        except Exception:
            pass
        result = ToolResult(
            content=f"Transfer requested to extension {target_extension}. Use {transfer_url}."
        )
        if self.tool_log is not None:
            self.tool_log.append(
                {
                    "tool_name": "transfer_to_human",
                    "arguments": {"reason": reason, "extension": target_extension},
                    "result": result.content,
                }
            )
        return result



TOOL_DEFS: List[Dict[str, Any]] = [
    {
        "name": "search_web",
        "description": "Search the web for mortgage programs and lending options.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "save_memory",
        "description": "Persist user preferences and facts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["role", "content"],
        },
    },
    {
        "name": "recall_memory",
        "description": "Recall recent user context from memory.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
        },
    },
    {
        "name": "upsert_mortgage_application",
        "description": "Create or update a mortgage application once core details are known.",
        "input_schema": {
            "type": "object",
            "properties": {
                "full_name": {"type": "string"},
                "date_of_birth": {"type": "string"},
                "credit_score": {"type": "integer"},
                "monthly_income": {"type": "number"},
                "down_payment_amount": {"type": "number"},
                "property_value": {"type": "number"},
            },
            "required": [
                "full_name",
                "date_of_birth",
                "credit_score",
                "monthly_income",
                "down_payment_amount",
                "property_value",
            ],
        },
    },
    {
        "name": "transfer_to_human",
        "description": "Transfer the caller to a human agent (extension 2001 by default).",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "extension": {"type": "string"},
            },
        },
    },
]
