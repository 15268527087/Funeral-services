"""进程内会话存储：最近 10 轮，阶段 2 替换为 Redis。"""

from __future__ import annotations

import threading
from typing import Any


class InMemorySessionStore:
    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self._sessions: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._sessions.get(session_id, []))

    def append(self, session_id: str, user_message: str, assistant_message: str) -> None:
        with self._lock:
            history = self._sessions.setdefault(session_id, [])
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": assistant_message})
            self._sessions[session_id] = history[-self.max_turns * 2 :]

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
