"""Shared LLM access — New Foundry Agent Service (Responses API).

Three named prompt agents (DM, Resolution, NPC) are registered in Foundry
and invoked via the Responses API. Each shows up as a distinct agent in the
Foundry portal with full traces.
"""

from __future__ import annotations

import json
import os

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

_project = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)
_client = _project.get_openai_client()

_AGENT_NAMES = {
    "dm":         "dm-agent",
    "resolution": "resolution-agent",
    "npc":        "npc-agent",
}
_DEFAULT_AGENT = "dm-agent"


def _invoke(agent_name: str, system: str, user: str) -> str:
    """Invoke a named Foundry prompt agent via the Responses API."""
    conversation = _client.conversations.create(
        items=[{
            "type": "message",
            "role": "user",
            "content": (
                f"<system_instructions>\n{system}\n</system_instructions>\n\n"
                f"<user_input>\n{user}\n</user_input>"
            ),
        }]
    )
    response = _client.responses.create(
        conversation=conversation.id,
        extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
    )
    return response.output_text or ""


def chat(system: str, user: str, json_mode: bool = False, caller: str | None = None) -> str:
    """Invoke the appropriate named Foundry agent. Returns response text."""
    agent_name = _AGENT_NAMES.get(caller or "", _DEFAULT_AGENT)
    return _invoke(agent_name, system, user)


def chat_json(system: str, user: str, caller: str | None = None) -> dict:
    """Chat that must return JSON. Tolerates markdown fences; retries once if the
    model returns malformed JSON, so a rare bad emission doesn't cost a whole turn."""
    for attempt in range(2):
        raw = chat(system, user, caller=caller)
        try:
            return _parse_json(raw)
        except (json.JSONDecodeError, ValueError):
            if attempt == 1:
                raise


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            return json.loads(raw[start:end + 1])
        raise