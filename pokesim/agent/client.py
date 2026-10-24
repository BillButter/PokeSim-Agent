"""A deliberately small OpenAI-compatible vision client.

No vendor SDK is used, so the same code works with Ollama, vLLM, LocalAI,
LM Studio, llama.cpp's server and hosted OpenAI-compatible gateways.  Only the
``/chat/completions`` contract and the OpenAI image_url content part are assumed.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import httpx

from .config import AgentConfig

log = logging.getLogger(__name__)


class AIClientError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def completion_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise AIClientError("No model endpoint is configured")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith(("/v1", "/openai")):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def models_url(base_url: str) -> str:
    return completion_url(base_url).removesuffix("/chat/completions") + "/models"


def image_part(png_base64: str) -> dict[str, Any]:
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{png_base64}"},
    }


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


class VisionClient:
    def __init__(self, config: AgentConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    async def complete(self, messages: list[dict[str, Any]]) -> str:
        url = completion_url(self.config.base_url)
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": 900,
            "stream": False,
        }
        timeout = httpx.Timeout(self.config.timeout, connect=min(15.0, self.config.timeout))
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    transport=self._transport,
                    follow_redirects=True,
                ) as client:
                    response = await client.post(url, json=payload, headers=self._headers())
                if response.status_code >= 400:
                    body = response.text[:1200]
                    error = AIClientError(
                        f"Model endpoint returned HTTP {response.status_code}: {body}",
                        status=response.status_code,
                        body=body,
                    )
                    # Retry rate limits and transient server failures once.
                    if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                        last_error = error
                        await asyncio.sleep(1.5)
                        continue
                    raise error
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    raise AIClientError(
                        "Model response had no choices", body=str(data)[:1200]
                    )
                choice = choices[0]
                message = choice.get("message") or {}
                text = _content_text(message.get("content"))
                if not text:
                    text = _content_text(choice.get("text"))
                if not text:
                    raise AIClientError(
                        "Model returned an empty message",
                        body=str(data)[:1200],
                    )
                return text
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = AIClientError(f"Could not reach the model endpoint: {exc}")
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                raise last_error from exc
            except AIClientError:
                raise
            except Exception as exc:
                raise AIClientError(f"Model request failed: {exc}") from exc
        raise last_error or AIClientError("Model request failed")

    async def test_connection(self) -> dict[str, Any]:
        """A cheap ``GET /v1/models`` health check used by the settings drawer."""
        url = models_url(self.config.base_url)
        timeout = httpx.Timeout(min(20.0, self.config.timeout), connect=10.0)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                transport=self._transport,
                follow_redirects=True,
            ) as client:
                response = await client.get(url, headers=self._headers())
        except Exception as exc:
            raise AIClientError(f"Could not reach {url}: {exc}") from exc
        if response.status_code >= 400:
            raise AIClientError(
                f"Endpoint returned HTTP {response.status_code}: {response.text[:500]}",
                status=response.status_code,
            )
        try:
            data = response.json()
        except ValueError:
            data = {}
        models = data.get("data") if isinstance(data, dict) else None
        names = []
        if isinstance(models, list):
            for item in models[:50]:
                if isinstance(item, dict):
                    name = item.get("id") or item.get("name")
                    if name:
                        names.append(str(name))
        return {"ok": True, "url": url, "models": names}


def png_data_url(png_base64: str) -> str:
    return "data:image/png;base64," + png_base64


def encode_png(image) -> str:
    """Encode a PIL image as the base64 payload used by the vision API."""
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
