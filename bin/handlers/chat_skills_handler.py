"""chat_skills_handler.py — CRUD for chat skills stored in KVStore."""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Tuple

from kvstore_client import KVStoreClient
from logger import get_logger

logger = get_logger(__name__)

COLLECTION = "chat_skills"


class ChatSkillsHandler:
    """Handles GET / POST / PUT / DELETE for chat_skills."""

    def __init__(self, session_key, username):
        # type: (str, str) -> None
        self._session_key = session_key
        self._username = username
        self._kv = KVStoreClient(session_key)

    def handle(self, method, payload):
        # type: (str, Dict[str, Any]) -> Tuple[Any, int]
        if method == "GET":
            return self._get_all(), 200
        if method == "POST":
            return self._create(payload)
        if method == "PUT":
            return self._update(payload)
        if method == "DELETE":
            return self._delete(payload)
        return {"error": "Method not allowed"}, 405

    def _get_all(self):
        # type: () -> List[Dict[str, Any]]
        try:
            records = self._kv.get_all(COLLECTION)
            normalized = [self._normalize(r) for r in records]
            return sorted(normalized, key=lambda r: r.get("sortOrder", 0))
        except Exception as exc:
            logger.error("Failed to read chat skills: %s", exc)
            return []

    def _create(self, payload):
        # type: (Dict[str, Any]) -> Tuple[Dict[str, Any], int]
        name = str(payload.get("name", "")).strip()
        if not name:
            return {"error": "Missing required field: name"}, 400

        skill_id = str(uuid.uuid4())
        existing = self._get_all()
        role = str(payload.get("role", "manager")).strip()
        is_sys = payload.get("isSystemPrompt", False)
        record = {
            "id": skill_id,
            "name": name,
            "prompt": str(payload.get("prompt", "")),
            "enabled": "1" if payload.get("enabled", True) else "0",
            "role": role if role in ("manager", "explainer", "writer", "validator") else "manager",
            "isSystemPrompt": "1" if is_sys in (True, "1", "true", "True") else "0",
            "createdBy": self._username,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sortOrder": len(existing),
        }
        self._kv.upsert(COLLECTION, skill_id, record)
        return self._normalize(record), 200

    def _update(self, payload):
        # type: (Dict[str, Any]) -> Tuple[Dict[str, Any], int]
        skill_id = str(payload.get("id", "")).strip()
        if not skill_id:
            return {"error": "Missing required field: id"}, 400
        try:
            existing = self._kv.get_by_id(COLLECTION, skill_id)
        except ValueError:
            return {"error": "Skill not found"}, 404

        if "name" in payload:
            existing["name"] = str(payload["name"]).strip()
        if "prompt" in payload:
            existing["prompt"] = str(payload["prompt"])
        if "enabled" in payload:
            existing["enabled"] = "1" if payload["enabled"] else "0"
        if "role" in payload:
            role = str(payload["role"]).strip()
            if role in ("manager", "explainer", "writer", "validator"):
                existing["role"] = role
        if "isSystemPrompt" in payload:
            is_sys = payload["isSystemPrompt"]
            existing["isSystemPrompt"] = "1" if is_sys in (True, "1", "true", "True") else "0"
        if "sortOrder" in payload:
            existing["sortOrder"] = int(payload["sortOrder"])

        self._kv.upsert(COLLECTION, skill_id, existing)
        return self._normalize(existing), 200

    def _delete(self, payload):
        # type: (Dict[str, Any]) -> Tuple[Dict[str, Any], int]
        skill_id = str(payload.get("id", "")).strip()
        if not skill_id:
            return {"error": "Missing required field: id"}, 400
        try:
            self._kv.delete(COLLECTION, skill_id)
            return {"status": "ok"}, 200
        except ValueError as exc:
            return {"error": str(exc)}, 404

    @staticmethod
    def _normalize(record):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        enabled_raw = record.get("enabled", "1")
        is_sys_raw = record.get("isSystemPrompt", "0")
        return {
            "id": record.get("id", ""),
            "name": record.get("name", ""),
            "prompt": record.get("prompt", ""),
            "enabled": enabled_raw in (True, "1", "true", "True"),
            "role": record.get("role", "manager"),
            "isSystemPrompt": is_sys_raw in (True, "1", "true", "True"),
            "createdBy": record.get("createdBy", ""),
            "createdAt": record.get("createdAt", ""),
            "sortOrder": int(record.get("sortOrder", 0)),
        }
