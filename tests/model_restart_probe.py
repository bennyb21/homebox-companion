"""Fresh-process offline wire probe; invoked by model configuration acceptance."""

import asyncio
import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import openai
from fastapi import FastAPI
from litellm.llms.openai.openai import OpenAIChatCompletion
from starlette.requests import Request

from homebox_companion.ai.llm import vision_completion
from homebox_companion.chat.llm_client import LLMClient
from homebox_companion.core import config
from homebox_companion.core import persistent_settings as ps
from homebox_companion.research import ProductIdentity
from server.api.config import get_config
from server.api.research import provider


async def main():
    ps.SETTINGS_FILE = Path(sys.argv[1])
    ps.clear_settings_cache()
    calls = []

    def forbid(*args, **kwargs):
        raise AssertionError("Offline probe cannot open a network socket")

    socket.socket.connect = forbid
    socket.socket.connect_ex = forbid

    def respond(request):
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer OWN-secret"
        calls.append({"url": str(request.url), "body": body})
        if request.url.path.endswith("/responses"):
            return httpx.Response(503, json={"error": {"message": "synthetic", "type": "server_error"}})
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    clients = []

    def sdk(_self, **kwargs):
        client = openai.AsyncOpenAI(
            api_key=kwargs["api_key"],
            base_url=kwargs["api_base"],
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        clients.append(client)
        return client

    sdk_patch = patch.object(OpenAIChatCompletion, "_get_openai_client", sdk)
    sdk_patch.start()
    app = FastAPI()
    app.state.settings = config.settings
    request = Request({"type": "http", "app": app})
    display = (await get_config(request)).model_dump()
    await vision_completion("Identify", "item", ["data:image/png;base64,c3ludGhldGlj"])
    await LLMClient().complete(
        [{"role": "user", "content": "Inspect"}],
        [
            {
                "type": "function",
                "function": {"name": "inspect_item", "parameters": {"type": "object", "properties": {}}},
            }
        ],
    )
    research = provider(request)
    research.transport = httpx.MockTransport(respond)
    result = await research.research(
        ProductIdentity(identifier_kind="part_number", identifier_exact="AB-123", identity_confirmed=True)
    )
    assert result.status == "unknown_outcome"
    for client in clients:
        await client.close()
    sdk_patch.stop()
    print(json.dumps({"model": display["llm_model"], "source": display["llm_model_source"], "calls": calls}))


if __name__ == "__main__":
    asyncio.run(main())
