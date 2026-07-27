from __future__ import annotations

import json
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, QThread, Signal


class OllamaError(Exception):
    pass


class OllamaNotRunning(OllamaError):
    pass


SYSTEM_SUFFIX = (
    "\n\nRules: Reply with ONLY the final text — no preamble, no explanations, "
    "no quotes around it. Write in the same language as the dictated text "
    "(Hebrew in → Hebrew out, English in → English out) unless the task above "
    "explicitly says otherwise."
)


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, payload: dict | None = None, timeout: float = 120.0):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower():
                raise OllamaNotRunning(
                    "Ollama is not running — start it with the Ollama app or `ollama serve`."
                ) from e
            raise OllamaError(f"Ollama request failed: {reason}") from e
        except json.JSONDecodeError as e:
            raise OllamaError(f"Ollama returned invalid JSON: {e}") from e

    def list_models(self) -> list[str]:
        data = self._request("/api/tags", timeout=5.0)
        return [m["name"] for m in data.get("models", []) if m.get("name")]

    def stream_pull(self, name: str):
        """Yield ``/api/pull`` progress lines (each a parsed JSON dict) as
        Ollama downloads ``name``, e.g. ``{"status": "pulling ...", "total":
        N, "completed": N}``. Raises ``OllamaError``/``OllamaNotRunning`` the
        same way ``_request`` does."""
        req = urllib.request.Request(
            f"{self.base_url}/api/pull",
            data=json.dumps({"name": name, "stream": True}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600.0) as resp:
                for raw_line in resp:
                    line = raw_line.decode().strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise OllamaError(data["error"])
                    yield data
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower():
                raise OllamaNotRunning(
                    "Ollama is not running — start it with the Ollama app or `ollama serve`."
                ) from e
            raise OllamaError(f"Ollama request failed: {reason}") from e
        except json.JSONDecodeError as e:
            raise OllamaError(f"Ollama returned invalid JSON: {e}") from e

    def rewrite(
        self,
        text: str,
        prompt: str,
        model: str,
        context: str = "",
    ) -> str:
        system = prompt.strip() + SYSTEM_SUFFIX
        user = text.strip()
        if context.strip():
            user = f"Context:\n{context.strip()}\n\nDictated text:\n{user}"
        data = self._request(
            "/api/chat",
            {
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=600.0,
        )
        content = (data.get("message") or {}).get("content", "")
        if not content.strip():
            raise OllamaError("Ollama returned an empty response.")
        return content.strip()


class OllamaPuller(QObject):
    """Pulls one Ollama model on a QThread. One instance per pull."""

    progress = Signal(int, int)  # bytes_done, bytes_total (total may be 0)
    status = Signal(str)  # human-readable status line, e.g. "pulling manifest"
    finished = Signal(str)  # the model name that was pulled
    error = Signal(str)

    def __init__(self, base_url: str, name: str) -> None:
        super().__init__()
        self.name = name
        self._base_url = base_url
        self._thread: QThread | None = None

    def start(self) -> None:
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self.finished.connect(self._thread.quit)
        self.error.connect(self._thread.quit)
        # Clean up only once the event loop has fully stopped, so the QThread
        # is never destroyed while still running (which would abort the app).
        self._thread.finished.connect(self.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _run(self) -> None:
        try:
            client = OllamaClient(self._base_url)
            for line in client.stream_pull(self.name):
                total = int(line.get("total") or 0)
                done = int(line.get("completed") or 0)
                if total:
                    self.progress.emit(done, total)
                status = line.get("status")
                if status:
                    self.status.emit(status)
            self.finished.emit(self.name)
        except OllamaError as e:
            self.error.emit(str(e))
