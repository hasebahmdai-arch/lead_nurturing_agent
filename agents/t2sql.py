from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import textwrap

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from vanna import Agent
from vanna.core.registry import ToolRegistry
from vanna.core.system_prompt.default import DefaultSystemPromptBuilder
from vanna.core.user import RequestContext, User, UserResolver
from vanna.integrations.google import GeminiLlmService
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.sqlite import SqliteRunner
from vanna.tools import RunSqlTool, VisualizeDataTool
from vanna.tools.agent_memory import (
    SaveQuestionToolArgsTool,
    SaveTextMemoryTool,
    SearchSavedCorrectToolUsesTool,
)


@dataclass
class TextToSQLResult:
    sql: str
    rows: List[Dict[str, Any]]
    explanation: str


class VannaTextToSQLService:
    class _RecordingRunSqlTool(RunSqlTool):
        """RunSqlTool that records executed SQL and rows into the parent service."""

        def __init__(self, *, service: "VannaTextToSQLService", sql_runner: SqliteRunner):
            super().__init__(sql_runner=sql_runner)
            self._service = service

        async def execute(self, context, args) -> Any:
            result = await super().execute(context, args)

            self._service._last_sql = args.sql
            # Capture results from metadata or UI component
            rows = result.metadata.get("results") if result.metadata else None
            if not rows and result.ui_component:
                rich = getattr(result.ui_component, "rich_component", None)
                rows = getattr(rich, "rows", None)

            if isinstance(rows, list):
                self._service._last_rows = rows
            else:
                self._service._last_rows = []

            self._service._last_message = result.result_for_llm
            return result

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ImproperlyConfigured(
                "GOOGLE_API_KEY must be set for Gemini-backed Text-to-SQL."
            )

        self._database_path = settings.BASE_DIR / "db.sqlite3"
        self._runner = SqliteRunner(database_path=str(self._database_path))

        self._last_sql: Optional[str] = None
        self._last_rows: List[Dict[str, Any]] = []
        self._last_message: str = ""

        self._schema_prompt = self._build_schema_prompt()

        llm_model = model or settings.VANNA_MODEL
        self._agent = self._build_agent(
            llm_model=llm_model, api_key=api_key, schema_prompt=self._schema_prompt
        )

    def _reset_state(self) -> None:
        self._last_sql = None
        self._last_rows = []
        self._last_message = ""

    def answer(self, question: str) -> TextToSQLResult:
        self._reset_state()
        try:
            return asyncio.run(self._run_agent(question))
        except RuntimeError:
            # Fallback if already inside an event loop
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._run_agent(question))
            finally:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

    async def _run_agent(self, question: str) -> TextToSQLResult:
        request_context = RequestContext()
        explanation_parts: List[str] = []

        async for component in self._agent.send_message(request_context, question):
            simple = getattr(component, "simple_component", None)
            if simple and getattr(simple, "text", None):
                explanation_parts.append(simple.text)

        if self._last_sql is None:
            self._last_sql = "/* SQL not generated */"

        explanation = (
            "\n".join(filter(None, explanation_parts)).strip()
            or self._last_message
            or "Assistant response unavailable."
        )
        return TextToSQLResult(
            sql=self._last_sql,
            rows=self._last_rows,
            explanation=explanation,
        )

    def _build_agent(self, *, llm_model: str, api_key: str, schema_prompt: str) -> Agent:
        llm_service = GeminiLlmService(model=llm_model, api_key=api_key, temperature=0.2)

        tools = ToolRegistry()
        tools.register_local_tool(
            self._RecordingRunSqlTool(service=self, sql_runner=self._runner),
            access_groups=["user", "admin"],
        )
        tools.register_local_tool(VisualizeDataTool(), access_groups=["user", "admin"])
        tools.register_local_tool(SaveTextMemoryTool(), access_groups=["admin", "user"])
        tools.register_local_tool(
            SaveQuestionToolArgsTool(), access_groups=["admin"]
        )
        tools.register_local_tool(
            SearchSavedCorrectToolUsesTool(), access_groups=["admin", "user"]
        )

        class StaticUserResolver(UserResolver):
            async def resolve_user(
                self, request_context: RequestContext
            ) -> User:
                return User(
                    id="system",
                    email="system@localhost",
                    group_memberships=["admin"],
                )

        agent_memory = DemoAgentMemory(max_items=500)
        return Agent(
            llm_service=llm_service,
            tool_registry=tools,
            user_resolver=StaticUserResolver(),
            agent_memory=agent_memory,
            system_prompt_builder=DefaultSystemPromptBuilder(base_prompt=schema_prompt),
        )

    def _build_schema_prompt(self) -> str:
        """Generate a concise system prompt that captures our SQLite schema."""
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()

        # Only document tables that are relevant to analytics questions.
        tables = [
            "crm_lead",
            "campaigns_campaign",
            "campaigns_campaignlead",
            "campaigns_conversationmessage",
        ]
        sections: List[str] = []

        for table in tables:
            try:
                cursor.execute(f"PRAGMA table_info({table})")
                rows = cursor.fetchall()
            except sqlite3.Error:
                continue

            if not rows:
                continue

            column_lines = [
                f"- {row['name']} ({row['type'] or 'TEXT'})"
                for row in rows
            ]
            sections.append(f"{table} columns:\n" + "\n".join(column_lines))

        cursor.close()
        connection.close()

        schema_description = "\n\n".join(sections) if sections else "Schema information unavailable."

        guidelines = textwrap.dedent(
            """
            Guidelines:
            - Prefer data from `crm_lead` for lead analytics. Budget information lives in `budget_min` and `budget_max`.
            - When asked for a single budget number, compute the average of available bounds, e.g. `AVG((budget_min + budget_max) / 2.0)`.
            - `status`, `project_enquired`, `unit_type`, and `last_conversation_date` are on `crm_lead`.
            - Join `campaigns_campaignlead` to relate campaigns and leads (`campaign_id` / `lead_id`).
            - Always generate valid SQLite-compatible SQL using the tables and columns documented here—avoid guessing table names.
            - If data is missing, explain it rather than fabricating numbers.
            """
        ).strip()

        return textwrap.dedent(
            f"""
            You are an analytics assistant for a real-estate CRM. Use SQL to answer questions.

            Database schema snapshot:
            {schema_description}

            {guidelines}
            """
        ).strip()

