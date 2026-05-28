import os

os.environ.setdefault("SCENARIO_LLM_MODE", "mock")

import pytest

from scenario_engine.llm_client import LLMClient, LLMMode
from scenario_engine.repair import Repair


@pytest.fixture
def repair():
    return Repair(LLMClient(mode=LLMMode.MOCK))


@pytest.mark.asyncio
async def test_parse_clean_json(repair):
    result = await repair.parse_turn_output(
        '{"narration":"ok","npc_dialogue":[],"state_delta":{},"next_options":["Continue"]}',
        context={},
    )
    assert result.narration == "ok"
    assert result.next_options == ["Continue"]


@pytest.mark.asyncio
async def test_parse_markdown_fenced_json(repair):
    result = await repair.parse_turn_output(
        '```json\n{"narration":"fenced","npc_dialogue":[],"state_delta":{},"next_options":["Continue"]}\n```',
        context={},
    )
    assert result.narration == "fenced"


@pytest.mark.asyncio
async def test_parse_text_before_after_json(repair):
    result = await repair.parse_turn_output(
        'Here you go: {"narration":"wrapped","npc_dialogue":[],"state_delta":{},"next_options":["Continue"]} thanks!',
        context={},
    )
    assert result.narration == "wrapped"


@pytest.mark.asyncio
async def test_malformed_output_falls_back(repair):
    class NoRepairClient(LLMClient):
        async def repair_json(self, broken_json: str, schema_hint: str = ""):
            del broken_json, schema_hint
            return None

    result = await Repair(NoRepairClient(mode=LLMMode.PIPER)).parse_turn_output(
        "not valid json at all",
        context={},
    )
    assert result.narration.startswith("Time passes.")
    assert result.next_options
