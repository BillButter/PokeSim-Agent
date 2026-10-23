from __future__ import annotations

import json

import httpx
import pytest

from app.agent.client import (
    AIClientError,
    VisionClient,
    completion_url,
    image_part,
    models_url,
)
from app.config import AIConfig


def test_url_normalisation():
    assert completion_url("http://localhost:11434") == "http://localhost:11434/v1/chat/completions"
    assert completion_url("http://localhost:11434/") == "http://localhost:11434/v1/chat/completions"
    assert completion_url("http://localhost:11434/v1") == "http://localhost:11434/v1/chat/completions"
    assert (
        completion_url("http://localhost:11434/v1/chat/completions")
        == "http://localhost:11434/v1/chat/completions"
    )
    assert models_url("http://localhost:11434/v1") == "http://localhost:11434/v1/models"
    with pytest.raises(AIClientError):
        completion_url("")


def test_image_part_is_an_openai_data_url():
    part = image_part("abc")
    assert part["type"] == "image_url"
    assert part["image_url"]["url"] == "data:image/png;base64,abc"


async def test_complete_posts_chat_completions_and_reads_list_content():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": '{"thought": "hi", '},
                                {"type": "text", "text": '"actions": [{"buttons": "a"}]}'},
                            ]
                        }
                    }
                ]
            },
        )

    config = AIConfig(base_url="http://model.test/v1", api_key="key", model="vision", timeout=5)
    client = VisionClient(config, transport=httpx.MockTransport(handler))
    text = await client.complete([{"role": "user", "content": "hello"}])

    assert text == '{"thought": "hi", "actions": [{"buttons": "a"}]}'
    assert captured["url"] == "http://model.test/v1/chat/completions"
    assert captured["auth"] == "Bearer key"
    assert captured["body"]["model"] == "vision"
    assert captured["body"]["stream"] is False


async def test_complete_raises_with_status_and_body():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    config = AIConfig(base_url="http://model.test/v1", model="vision", timeout=5)
    client = VisionClient(config, transport=httpx.MockTransport(handler))
    with pytest.raises(AIClientError) as excinfo:
        await client.complete([])
    assert excinfo.value.status == 401
    assert "bad key" in str(excinfo.value)


async def test_test_connection_lists_models():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/v1/models")
        return httpx.Response(200, json={"data": [{"id": "llava"}, {"id": "other"}]})

    config = AIConfig(base_url="http://model.test", model="llava", timeout=5)
    result = await VisionClient(config, transport=httpx.MockTransport(handler)).test_connection()
    assert result["ok"] is True
    assert result["models"] == ["llava", "other"]
    assert result["url"] == "http://model.test/v1/models"
