from __future__ import annotations

import json
import urllib.error
import urllib.request


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
