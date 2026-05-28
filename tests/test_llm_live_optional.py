import os

os.environ.setdefault("SCENARIO_LLM_MODE", "mock")

import pytest

from scenario_engine.llm_client import LLMMode, PiperLLMAdapter
from scenario_engine.engine import ScenarioEngine
from scenario_engine.models import TurnInput
from scenario_engine.storage import Storage


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("SCENARIO_LIVE_LLM_TESTS") != "1",
    reason="live LLM smoke tests require SCENARIO_LIVE_LLM_TESTS=1",
)
async def test_live_llm_turn_smoke():
    engine = ScenarioEngine(
        storage=Storage("scenarios", "sessions"),
        llm_client=PiperLLMAdapter(config={}),
    )
    await engine.load_scenario("tiny_fantasy_sample")
    result = await engine.take_turn(TurnInput(user_input="Look around the square"))
    assert result.narration
    assert result.next_options

@pytest.mark.asyncio
async def test_piper_mode_falls_back_without_server():
    engine = ScenarioEngine(
        storage=Storage("scenarios", "sessions"),
        llm_client=PiperLLMAdapter(
            config={
                "base_url": "http://127.0.0.1:1",
                "model": "qwen",
                "timeout_seconds": 0.1,
            }
        ),
    )
    await engine.load_scenario("tiny_fantasy_sample")
    result = await engine.take_turn(TurnInput(user_input="Look around the square"))
    assert result.narration
    assert result.next_options
