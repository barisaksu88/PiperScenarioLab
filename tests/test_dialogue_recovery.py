import os

os.environ.setdefault("SCENARIO_LLM_MODE", "mock")

import pytest

from scenario_engine.engine import ScenarioEngine
from scenario_engine.llm_client import LLMClient, LLMMode
from scenario_engine.models import TurnInput
from scenario_engine.storage import Storage


class NoDialogueMockClient(LLMClient):
    async def generate_turn(self, prompt, scenario, context):  # noqa: D401
        del prompt, scenario, context
        from scenario_engine.models import StateDelta, TurnProposal

        return TurnProposal(
            narration="Mara studies you for a moment, clearly ready to answer.",
            npc_dialogue=[],
            state_delta=StateDelta(),
            next_options=["Ask Mara another question"],
        )

    async def generate_dialogue(self, prompt, scenario, context):
        del prompt, scenario, context
        return [
            {
                "speaker_id": "mara_bellkeeper",
                "speaker_name": "Mara",
                "role": "Bellkeeper",
                "tone": "cautious",
                "text": "The bell has been silent for a reason, and I think you already sense it.",
            }
        ]


@pytest.mark.asyncio
async def test_recover_missing_dialogue_from_conversational_turn():
    engine = ScenarioEngine(
        storage=Storage("scenarios", "sessions"),
        llm_client=NoDialogueMockClient(mode=LLMMode.MOCK),
    )
    await engine.load_scenario("tiny_fantasy_sample")
    result = await engine.take_turn(TurnInput(user_input="Ask Mara about the bell"))
    assert result.npc_dialogue
    assert result.npc_dialogue[0].speaker_name == "Mara"


@pytest.mark.asyncio
async def test_direct_conversation_turn_recovers_dialogue():
    engine = ScenarioEngine(
        storage=Storage("scenarios", "sessions"),
        llm_client=NoDialogueMockClient(mode=LLMMode.MOCK),
    )
    await engine.load_scenario("tiny_fantasy_sample")
    result = await engine.take_turn(TurnInput(user_input="Ask Mara about the bell."))
    assert result.narration
    assert result.npc_dialogue


def test_fallback_dialogue_varies_by_input():
    from scenario_engine.models import NPC, NPCPersona
    engine = ScenarioEngine(
        storage=Storage("scenarios", "sessions"),
        llm_client=NoDialogueMockClient(mode=LLMMode.MOCK),
    )
    npc = NPC(
        id="npc_test",
        name="Test",
        role="Guide",
        persona=NPCPersona(temperament="cautious", motives=["protect the secret"], fears=["discovery"]),
    )
    # Different inputs should produce different persona-appropriate responses
    intro_text, intro_tone = engine._fallback_dialogue_text("Who are you?", npc)
    help_text, help_tone = engine._fallback_dialogue_text("Help me!", npc)
    assert intro_text != help_text
    assert "Test" in intro_text
    assert "cautious" in intro_tone or "guarded" in intro_tone or "calm" in intro_tone
