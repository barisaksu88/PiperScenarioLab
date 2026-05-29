"""Tests for scenario generator with mocked LLM responses."""

import json
from unittest.mock import patch
import pytest

from scenario_engine.scenario_generator import ScenarioGenerator


@pytest.fixture
def generator():
    return ScenarioGenerator(base_url="http://127.0.0.1:8080", model="qwen")


def _mock_post_json(payload):
    content = payload["messages"][1]["content"]
    if "scenario premise" in content.lower():
        return {
            "choices": [{"message": {"content": json.dumps({
                "title": "Test Tale",
                "description": "A test description.",
                "genre": "fantasy",
                "estimated_duration_minutes": 15,
                "num_acts": 2,
                "overall_arc": "Start to end.",
                "opening_scene_description": "You wake up.",
                "ending_scene_description": "You win."
            })}}]
        }
    if "npcs, items, and skills" in content.lower():
        return {
            "choices": [{"message": {"content": json.dumps({
                "npcs": [
                    {
                        "id": "npc_test",
                        "name": "Test NPC",
                        "role": "Guide",
                        "current_scene": "",
                        "persona": {
                            "voice": "calm",
                            "motives": ["help"],
                            "fears": ["darkness"],
                            "temperament": "kind",
                            "speech_style": "short"
                        },
                        "relationship_to_player": {"trust": 10, "fear": 0, "hostility": 0, "respect": 5},
                        "knows": ["secret"],
                        "can_reveal": ["secret"],
                        "triggers": [],
                        "status": "available"
                    }
                ],
                "items": [
                    {"id": "item_test", "name": "Test Item", "description": "A test item.", "category": "general"}
                ],
                "skills": [
                    {"id": "skill_test", "name": "Test Skill", "description": "A test skill.", "category": "general"}
                ]
            })}}]
        }
    if "design the act/scene structure" in content.lower():
        return {
            "choices": [{"message": {"content": json.dumps({
                "acts": [
                    {
                        "id": "act_1",
                        "name": "Act One",
                        "description": "First",
                        "scenes": [
                            {
                                "id": "scene_1",
                                "name": "Start",
                                "description": "You are here.",
                                "connected_scenes": ["scene_2"],
                                "npcs_present": ["npc_test"],
                                "items_present": ["item_test"],
                                "clues_present": ["clue_1"]
                            },
                            {
                                "id": "scene_2",
                                "name": "End",
                                "description": "The end.",
                                "connected_scenes": ["scene_1"],
                                "npcs_present": [],
                                "items_present": [],
                                "clues_present": []
                            }
                        ],
                        "objectives": [
                            {"id": "obj_1", "description": "Find the item.", "required_flags": [], "required_clues": ["clue_1"]}
                        ],
                        "completion_flags": ["act1_done"],
                        "ending_narration": ""
                    },
                    {
                        "id": "act_2",
                        "name": "Act Two",
                        "description": "Second",
                        "scenes": [
                            {
                                "id": "scene_3",
                                "name": "Finale",
                                "description": "Final scene.",
                                "connected_scenes": [],
                                "npcs_present": [],
                                "items_present": [],
                                "clues_present": []
                            }
                        ],
                        "objectives": [],
                        "completion_flags": ["act2_done"],
                        "ending_narration": "The story concludes."
                    }
                ]
            })}}]
        }
    raise ValueError(f"Unexpected prompt: {content[:200]}")


@pytest.mark.asyncio
async def test_generate_scenario(generator):
    with patch.object(generator, "_post_json", side_effect=_mock_post_json):
        scenario = await generator.generate(
            title_hint="",
            genre="fantasy",
            length="short",
            difficulty="easy",
            tone="mysterious",
            theme="A test theme"
        )
    assert scenario.metadata.title == "Test Tale"
    assert len(scenario.acts) == 2
    assert "npc_test" in scenario.npcs
    assert "item_test" in scenario.items
    assert "skill_test" in scenario.skills
    # Scene references sanitized
    for act in scenario.acts.values():
        for scene in act.scenes.values():
            for npc_id in scene.npcs_present:
                assert npc_id in scenario.npcs
            for item_id in scene.items_present:
                assert item_id in scenario.items
    assert scenario.player.current_act == "act_1"
    assert scenario.player.current_scene == "scene_1"
    # Scene graph should be fully connected (disconnected scenes auto-fixed)
    all_scenes = {}
    for act in scenario.acts.values():
        all_scenes.update(act.scenes)
    # Every scene except the first must have at least one connection
    first_scene_id = scenario.player.current_scene
    for sid, scene in all_scenes.items():
        if sid == first_scene_id:
            continue
        assert scene.connected_scenes, f"Scene {sid} has no connections"
    # Cross-act connectivity: scene_3 should connect back to a scene in act_1
    scene_3 = scenario.acts["act_2"].scenes["scene_3"]
    assert any(sid in scenario.acts["act_1"].scenes for sid in scene_3.connected_scenes)


def test_complete_truncated_json_unclosed_string():
    """Truncated JSON ending inside a string should be repaired."""
    truncated = '{"acts": [{"id": "act_1", "name": "Act", "description": "The protagonist stands atop the cru'
    result = ScenarioGenerator._complete_truncated_json(truncated)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["acts"][0]["id"] == "act_1"


def test_complete_truncated_json_unclosed_object():
    """Truncated JSON ending after an unclosed object should be repaired."""
    truncated = '{"acts": [{"id": "act_1", "name": "Act"'
    result = ScenarioGenerator._complete_truncated_json(truncated)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["acts"][0]["id"] == "act_1"


def test_complete_truncated_json_balanced():
    """Already valid JSON should pass through unchanged."""
    valid = '{"acts": [{"id": "act_1"}]}'
    result = ScenarioGenerator._complete_truncated_json(valid)
    assert result == valid


def test_complete_truncated_json_no_brace():
    """Text with no opening brace should return None."""
    assert ScenarioGenerator._complete_truncated_json("not json") is None
