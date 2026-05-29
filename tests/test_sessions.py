"""Tests for session persistence and engine load_session."""

import json
import os
import pytest

from scenario_engine.engine import ScenarioEngine
from scenario_engine.llm_client import LLMClient, LLMMode
from scenario_engine.models import TurnInput
from scenario_engine.storage import Storage


@pytest.fixture
def engine(tmp_path):
    storage = Storage(
        scenarios_dir=str(tmp_path / "scenarios"),
        sessions_dir=str(tmp_path / "sessions"),
    )
    scenarios_dir = tmp_path / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    scenarios_dir.joinpath("tiny_fantasy_sample.json").write_text(
        """{
  "metadata": {"title": "Tiny Fantasy", "difficulty": "easy", "profile_id": "fantasy_tiny"},
  "profile": {"profile_id": "fantasy_tiny", "display_name": "Tiny Fantasy", "allowed_dynamic_creation": ["flags"], "validation_rules": {}, "prompt_template_dir": "", "ui_labels": {}, "state_extensions": {}},
  "acts": {
    "act_1": {
      "id": "act_1", "name": "Act 1", "description": "", "scenes": {
        "scene_1": {"id": "scene_1", "name": "Scene 1", "description": "", "connected_scenes": [], "npcs_present": [], "items_present": [], "clues_present": []}
      },
      "objectives": {}, "completion_flags": []
    }
  },
  "npcs": {}, "items": {}, "skills": {},
  "player": {"current_act": "act_1", "current_scene": "scene_1", "inventory": [], "skills": [], "clues": [], "flags": {}},
  "global_flags": {}
}""",
        encoding="utf-8",
    )
    client = LLMClient(mode=LLMMode.MOCK)
    eng = ScenarioEngine(storage=storage, llm_client=client)
    return eng


@pytest.mark.asyncio
async def test_save_and_list_sessions(engine):
    await engine.load_scenario("tiny_fantasy_sample")
    sessions = engine.storage.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["scenario_id"] == "tiny_fantasy_sample"
    assert sessions[0]["turn_number"] == 0


@pytest.mark.asyncio
async def test_load_session(engine):
    await engine.load_scenario("tiny_fantasy_sample")
    await engine.take_turn(TurnInput(user_input="look around"))
    session_id = engine.session_id

    # Create fresh engine and load session
    fresh = ScenarioEngine(storage=engine.storage, llm_client=engine.llm_client)
    await fresh.load_session(session_id)
    assert fresh.turn_number == 1
    assert fresh.session_id == session_id


@pytest.mark.asyncio
async def test_delete_session(engine):
    await engine.load_scenario("tiny_fantasy_sample")
    session_id = engine.session_id
    assert engine.storage.delete_session(session_id) is True
    assert engine.storage.list_sessions() == []


@pytest.mark.asyncio
async def test_load_missing_session(engine):
    with pytest.raises(FileNotFoundError):
        await engine.load_session("sess_doesnotexist")


@pytest.mark.asyncio
async def test_load_session_preserves_full_state(engine):
    """Objectives, NPC locations, and relationships must survive save/load."""
    from scenario_engine.models import Objective, NPC, NPCPersona, NPCRelationship
    await engine.load_scenario("tiny_fantasy_sample")
    # Manually mutate scenario state as if a turn happened
    engine.scenario.acts["act_1"].objectives["obj_test"] = Objective(
        id="obj_test",
        description="Test objective",
        status="complete",
    )
    engine.scenario.npcs["npc_test"] = NPC(
        id="npc_test",
        name="Test NPC",
        role="Guide",
        current_scene="scene_1",
        persona=NPCPersona(voice="calm", motives=[], fears=[], temperament="kind", speech_style="short"),
        relationship_to_player=NPCRelationship(trust=25, fear=0, hostility=0, respect=10),
    )
    engine.scenario.player.flags["found_secret"] = True
    engine.turn_number = 3
    session_id = engine.session_id

    # Save
    session_state = engine._build_session_state_dict()
    engine.storage.save_session(session_id, session_state)

    # Load into fresh engine
    fresh = ScenarioEngine(storage=engine.storage, llm_client=engine.llm_client)
    await fresh.load_session(session_id)

    assert fresh.turn_number == 3
    assert fresh.scenario.player.flags.get("found_secret") is True
    assert fresh.scenario.acts["act_1"].objectives["obj_test"].status == "complete"
    assert fresh.scenario.npcs["npc_test"].current_scene == "scene_1"
    assert fresh.scenario.npcs["npc_test"].relationship_to_player.trust == 25
