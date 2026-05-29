"""Tests for act progression and ending detection."""

import pytest

from scenario_engine.engine import ScenarioEngine
from scenario_engine.llm_client import LLMClient, LLMMode
from scenario_engine.models import TurnInput
from scenario_engine.storage import Storage


@pytest.fixture
def progression_engine(tmp_path):
    storage = Storage(
        scenarios_dir=str(tmp_path / "scenarios"),
        sessions_dir=str(tmp_path / "sessions"),
    )
    scenarios_dir = tmp_path / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    scenarios_dir.joinpath("progression_test.json").write_text(
        """{
  "metadata": {"title": "Progression Test", "difficulty": "easy", "profile_id": "test"},
  "profile": {"profile_id": "test", "display_name": "Test", "allowed_dynamic_creation": ["flags"], "validation_rules": {}, "prompt_template_dir": "", "ui_labels": {}, "state_extensions": {}},
  "acts": {
    "act_1": {
      "id": "act_1", "name": "Act One", "description": "First act", "scenes": {
        "scene_a": {"id": "scene_a", "name": "Scene A", "description": "", "connected_scenes": ["scene_b"], "npcs_present": [], "items_present": [], "clues_present": []},
        "scene_b": {"id": "scene_b", "name": "Scene B", "description": "", "connected_scenes": ["scene_a"], "npcs_present": [], "items_present": [], "clues_present": []}
      },
      "objectives": {}, "completion_flags": ["act1_done"]
    },
    "act_2": {
      "id": "act_2", "name": "Act Two", "description": "Second act", "scenes": {
        "scene_c": {"id": "scene_c", "name": "Scene C", "description": "", "connected_scenes": [], "npcs_present": [], "items_present": [], "clues_present": []}
      },
      "objectives": {}, "completion_flags": ["act2_done"],
      "ending_narration": "The journey ends in triumph."
    }
  },
  "npcs": {}, "items": {}, "skills": {},
  "player": {"current_act": "act_1", "current_scene": "scene_a", "inventory": [], "skills": [], "clues": [], "flags": {}},
  "global_flags": {}
}""",
        encoding="utf-8",
    )
    client = LLMClient(mode=LLMMode.MOCK)
    return ScenarioEngine(storage=storage, llm_client=client)


@pytest.mark.asyncio
async def test_act_progression(progression_engine):
    engine = progression_engine
    await engine.load_scenario("progression_test")
    # Mock mode will produce state deltas; we manually set the flag to test progression
    engine.scenario.player.flags["act1_done"] = True
    result = await engine.take_turn(TurnInput(user_input="advance"))
    # Should have transitioned to act 2
    assert engine.scenario.player.current_act == "act_2"
    assert engine.scenario.player.current_scene == "scene_c"
    assert "Act Two" in result.narration
    assert result.ending is None
    # Runtime fix: new scene should connect back to previous scene so player isn't trapped
    scene_c = engine.scenario.acts["act_2"].scenes["scene_c"]
    # Player was in scene_a when progression triggered, so scene_c should link back to scene_a
    assert "scene_a" in scene_c.connected_scenes


@pytest.mark.asyncio
async def test_ending_detection(progression_engine):
    engine = progression_engine
    await engine.load_scenario("progression_test")
    engine.scenario.player.current_act = "act_2"
    engine.scenario.player.current_scene = "scene_c"
    engine.scenario.player.flags["act2_done"] = True
    result = await engine.take_turn(TurnInput(user_input="finish"))
    assert result.ending == "The journey ends in triumph."


@pytest.mark.asyncio
async def test_get_state_shows_ending(progression_engine):
    engine = progression_engine
    await engine.load_scenario("progression_test")
    engine.scenario.player.current_act = "act_2"
    engine.scenario.player.current_scene = "scene_c"
    engine.scenario.player.flags["act2_done"] = True
    state = engine.get_state()
    assert state.ending == "The journey ends in triumph."
