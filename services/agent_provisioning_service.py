"""Agent provisioning service for OpenAI Assistants."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet

from core.settings import settings

logger = logging.getLogger(__name__)

try:
    from services.agent_logger import agent_logger, AgentEventType
except ImportError:  # pragma: no cover - optional dependency
    agent_logger = None
    AgentEventType = None


def _load_cipher() -> Fernet:
    key = os.getenv("AGENT_KEY_ENCRYPTION_KEY") or os.getenv("DATA_ENCRYPTION_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        logger.warning(
            "Generated temporary encryption key for agent provisioning. "
            "Set AGENT_KEY_ENCRYPTION_KEY to persist secrets across restarts."
        )
    if isinstance(key, str):
        # Add padding if missing (common issue with base64 keys)
        missing_padding = len(key) % 4
        if missing_padding:
            key += '=' * (4 - missing_padding)
        key = key.encode()
    return Fernet(key)


_CIPHER = _load_cipher()


@dataclass
class ProvisionedAgent:
    assistant_id: str
    signature: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentProvisioningService:
    """Handles creation, rotation, and storage of OpenAI assistant IDs."""

    TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS ai_assistants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        assistant_id_encrypted TEXT NOT NULL,
        signature TEXT NOT NULL,
        metadata TEXT,
        version INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(tenant_id, role)
    );
    """

    def __init__(self):
        self._table_ready = False
        self._locks: Dict[str, asyncio.Lock] = {}

    async def ensure_agent(
        self,
        tenant_id: int,
        role: str,
        config_payload: Dict[str, Any],
        *,
        force_rotate: bool = False,
        api_key: Optional[str] = None,
        organization: Optional[str] = None,
    ) -> ProvisionedAgent:
        """
        Ensure an assistant exists for the tenant/role combination.

        Args:
            tenant_id: Tenant identifier.
            role: Agent role key (e.g., "workflow_orchestrator").
            config_payload: Dict containing name, instructions, model, tools.
            force_rotate: When True, always create a new assistant.
            api_key: OpenAI API key override.
            organization: OpenAI organization override.
        Returns:
            ProvisionedAgent metadata containing assistant ID and signature.
        """

        lock = self._locks.setdefault(f"{tenant_id}:{role}", asyncio.Lock())
        async with lock:
            record = await asyncio.get_event_loop().run_in_executor(
                None,
                self._get_agent_record,
                tenant_id,
                role,
            )

            signature = self._compute_signature(config_payload)

            if record and not force_rotate and record.signature == signature:
                return ProvisionedAgent(
                    assistant_id=record.assistant_id,
                    signature=record.signature,
                    metadata=record.metadata,
                )

            assistant = await self._create_openai_assistant(
                config_payload,
                api_key=api_key,
                organization=organization,
            )

            assistant_id = assistant.get("id") or assistant.get("assistant_id")
            if not assistant_id:
                raise RuntimeError("OpenAI assistant creation did not return an ID")

            metadata = {
                "name": assistant.get("name"),
                "model": assistant.get("model"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            await asyncio.get_event_loop().run_in_executor(
                None,
                self._upsert_agent_record,
                tenant_id,
                role,
                assistant_id,
                signature,
                metadata,
            )

            if agent_logger and AgentEventType:
                await agent_logger.log_event(
                    agent_id="agent_provisioning",
                    event_type=AgentEventType.SYSTEM_EVENT,
                    message=f"Provisioned assistant {assistant_id} for role {role}",
                    metadata={
                        "tenant_id": tenant_id,
                        "signature": signature,
                        "model": metadata.get("model"),
                    },
                )

            return ProvisionedAgent(
                assistant_id=assistant_id,
                signature=signature,
                metadata=metadata,
            )

    async def rotate_agent(
        self,
        tenant_id: int,
        role: str,
        config_payload: Dict[str, Any],
        *,
        api_key: Optional[str] = None,
        organization: Optional[str] = None,
    ) -> ProvisionedAgent:
        """Force creation of a new assistant for the given role."""

        return await self.ensure_agent(
            tenant_id,
            role,
            config_payload,
            force_rotate=True,
            api_key=api_key,
            organization=organization,
        )

    async def list_agents(self, tenant_id: int) -> Dict[str, ProvisionedAgent]:
        """Return all stored assistants for a tenant keyed by role."""

        records = await asyncio.get_event_loop().run_in_executor(
            None,
            self._list_agent_records,
            tenant_id,
        )
        return records

    def _ensure_table(self):
        if self._table_ready:
            return

        from api.db_core import get_conn

        with get_conn() as conn:
            conn.executescript(self.TABLE_SQL)
        self._table_ready = True

    def _get_agent_record(self, tenant_id: int, role: str):
        self._ensure_table()

        from api.db_core import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT assistant_id_encrypted, signature, metadata FROM ai_assistants WHERE tenant_id = ? AND role = ?",
                (tenant_id, role),
            ).fetchone()

        if not row:
            return None

        assistant_id = self._decrypt(row[0])
        metadata = json.loads(row[2]) if row[2] else {}
        return ProvisionedAgent(
            assistant_id=assistant_id,
            signature=row[1],
            metadata=metadata,
        )

    def _upsert_agent_record(
        self,
        tenant_id: int,
        role: str,
        assistant_id: str,
        signature: str,
        metadata: Dict[str, Any],
    ) -> None:
        self._ensure_table()

        from api.db_core import get_conn

        encrypted = self._encrypt(assistant_id)
        metadata_json = json.dumps(metadata)

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO ai_assistants (tenant_id, role, assistant_id_encrypted, signature, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, role) DO UPDATE SET
                    assistant_id_encrypted = excluded.assistant_id_encrypted,
                    signature = excluded.signature,
                    metadata = excluded.metadata,
                    version = ai_assistants.version + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (tenant_id, role, encrypted, signature, metadata_json),
            )

    def _list_agent_records(self, tenant_id: int) -> Dict[str, ProvisionedAgent]:
        self._ensure_table()

        from api.db_core import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT role, assistant_id_encrypted, signature, metadata FROM ai_assistants WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchall()

        records: Dict[str, ProvisionedAgent] = {}
        for role, enc_id, signature, metadata_json in rows:
            assistant_id = self._decrypt(enc_id)
            metadata = json.loads(metadata_json) if metadata_json else {}
            records[role] = ProvisionedAgent(
                assistant_id=assistant_id,
                signature=signature,
                metadata=metadata,
            )
        return records

    async def _create_openai_assistant(
        self,
        config_payload: Dict[str, Any],
        *,
        api_key: Optional[str],
        organization: Optional[str],
    ) -> Dict[str, Any]:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - dependency missing in some envs
            raise RuntimeError("OpenAI SDK is not installed") from exc

        client = AsyncOpenAI(
            api_key=api_key or settings.OPENAI_API_KEY,
            organization=organization,
        )

        try:
            tools = config_payload.get("tools") or []
            assistant = await client.beta.assistants.create(
                name=config_payload.get("name"),
                instructions=config_payload.get("instructions"),
                model=config_payload.get("model") or settings.OPENAI_MODEL,
                tools=tools,
                temperature=config_payload.get("temperature", 0.2),
            )

            if hasattr(assistant, "model_dump"):
                return assistant.model_dump()
            if hasattr(assistant, "dict"):
                return assistant.dict()
            return assistant
        finally:
            try:
                await client.close()
            except Exception:
                pass

    def _compute_signature(self, config_payload: Dict[str, Any]) -> str:
        tools_raw = config_payload.get("tools") or []

        def _normalize_tool(tool: Any) -> Any:
            if isinstance(tool, dict):
                return tool
            name = getattr(tool, "name", None)
            if name:
                return {"name": name}
            return str(tool)

        payload = {
            "name": config_payload.get("name"),
            "model": config_payload.get("model"),
            "instructions": config_payload.get("instructions"),
            "tools": [_normalize_tool(t) for t in tools_raw],
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _encrypt(self, value: str) -> str:
        return _CIPHER.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        return _CIPHER.decrypt(value.encode()).decode()


agent_provisioning_service = AgentProvisioningService()

__all__ = ["AgentProvisioningService", "agent_provisioning_service", "ProvisionedAgent"]