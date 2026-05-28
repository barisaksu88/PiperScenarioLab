import pytest
from pydantic import ValidationError
from scenario_engine.models import *


def test_npc_relationship_bounds():
    rel = NPCRelationship(trust=50, fear=-30, hostility=10, respect=75)
    assert rel.trust == 50
    assert rel.fear == -30
    assert rel.hostility == 10
    assert rel.respect == 75

    # Edge cases at -100 and 100
    rel_min = NPCRelationship(trust=-100, fear=-100, hostility=-100, respect=-100)
    assert rel_min.trust == -100
    rel_max = NPCRelationship(trust=100, fear=100, hostility=100, respect=100)
    assert rel_max.trust == 100

    # Pydantic validates out-of-range
    with pytest.raises(ValidationError):
        NPCRelationship(trust=101)
    with pytest.raises(ValidationError):
        NPCRelationship(trust=-101)


def test_dialogue_line_creation():
    line = DialogueLine(
        speaker_id="mara_bellkeeper",
        speaker_name="Mara",
        role="Bellkeeper",
        tone="guarded",
        text="Some things are better left unspoken.",
    )
    assert line.speaker_id == "mara_bellkeeper"
    assert line.speaker_name == "Mara"
    assert line.role == "Bellkeeper"
    assert line.tone == "guarded"
    assert line.text == "Some things are better left unspoken."


def test_scenario_from_json():
    import json
    from pathlib import Path

    path = Path("scenarios") / "tiny_fantasy_sample.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    scenario = Scenario.model_validate(raw)

    # Top-level fields
    assert scenario.metadata.title == "The Bellkeeper's Secret"
    assert scenario.metadata.author == "PiperScenarioLab"
    assert scenario.metadata.version == "1.0"
    assert scenario.profile.profile_id == "fantasy_tiny"
    assert len(scenario.acts) >= 1
    assert len(scenario.npcs) >= 1
    assert len(scenario.items) >= 1
    assert len(scenario.skills) >= 1
    assert scenario.player is not None


def test_nested_models():
    npc = NPC(
        id="mara_bellkeeper",
        name="Mara",
        role="Bellkeeper",
        current_scene="village_square",
        persona=NPCPersona(voice="guarded", motives=["protect the bell"]),
        relationship_to_player=NPCRelationship(trust=10),
    )
    scene = Scene(
        id="village_square",
        name="Village Square",
        npcs_present=["mara_bellkeeper"],
        items_present=["lantern"],
        clues_present=["ash_symbol"],
    )
    act = Act(id="act1", name="Arrival", scenes={"village_square": scene})
    item = Item(id="lantern", name="Lantern", category="tool")
    skill = Skill(id="perception", name="Perception")
    player = PlayerState(
        current_act="act1",
        current_scene="village_square",
        inventory=["lantern"],
        skills=["perception"],
        clues=["ash_symbol"],
        flags={"met_mara": True},
    )
    meta = ScenarioMetadata(title="Test", profile_id="fantasy_tiny")
    profile = ScenarioProfile(profile_id="fantasy_tiny", display_name="Test")
    scenario = Scenario(
        metadata=meta,
        profile=profile,
        acts={"act1": act},
        npcs={"mara_bellkeeper": npc},
        items={"lantern": item},
        skills={"perception": skill},
        player=player,
    )
    assert scenario.acts["act1"].scenes["village_square"].npcs_present == ["mara_bellkeeper"]
    assert scenario.npcs["mara_bellkeeper"].relationship_to_player.trust == 10


def test_player_state_defaults():
    ps = PlayerState()
    assert ps.current_act == ""
    assert ps.current_scene == ""
    assert ps.inventory == []
    assert ps.skills == []
    assert ps.clues == []
    assert ps.flags == {}


def test_turn_proposal_validation():
    proposal = TurnProposal(
        narration="The village square is quiet.",
        npc_dialogue=[
            DialogueLine(
                speaker_id="mara_bellkeeper",
                speaker_name="Mara",
                role="Bellkeeper",
                tone="guarded",
                text="You're new here.",
            )
        ],
        state_delta=StateDelta(
            flags={"met_mara": True},
            inventory_add=["lantern"],
            clues_add=["ash_symbol"],
            relationship_changes=[{"npc_id": "mara_bellkeeper", "trust": 5}],
        ),
        next_options=["Look around", "Talk to Mara", "Go north"],
    )
    assert proposal.narration == "The village square is quiet."
    assert len(proposal.npc_dialogue) == 1
    assert proposal.state_delta.flags == {"met_mara": True}
    assert len(proposal.next_options) == 3


def test_state_delta_operations():
    delta = StateDelta(
        flags={"met_mara": True, "found_key": False},
        inventory_add=["lantern"],
        inventory_remove=["old_item"],
        clues_add=["ash_symbol", "old_tracks"],
        skills_add=["perception"],
        relationship_changes=[
            {"npc_id": "mara_bellkeeper", "trust": 10, "respect": 5},
            {"npc_id": "eldric_mayor", "trust": -5, "hostility": 10},
        ],
        move_player_to_scene="bell_tower",
        move_npc_to_scene=[{"npc_id": "mara_bellkeeper", "scene_id": "bell_tower"}],
        complete_objectives=["obj1"],
        fail_objectives=["obj2"],
        npc_status_changes={"eldric_mayor": "hostile"},
    )
    assert delta.flags == {"met_mara": True, "found_key": False}
    assert delta.inventory_add == ["lantern"]
    assert delta.inventory_remove == ["old_item"]
    assert delta.clues_add == ["ash_symbol", "old_tracks"]
    assert delta.skills_add == ["perception"]
    assert len(delta.relationship_changes) == 2
    assert delta.move_player_to_scene == "bell_tower"
    assert len(delta.move_npc_to_scene) == 1
    assert delta.complete_objectives == ["obj1"]
    assert delta.fail_objectives == ["obj2"]
    assert delta.npc_status_changes == {"eldric_mayor": "hostile"}


def test_validation_result():
    result = ValidationResult(
        is_valid=False,
        accepted_delta=StateDelta(flags={"met_mara": True}),
        rejected_changes=[
            {"field": "inventory_add", "value": "fake_item", "reason": "Item not found"}
        ],
        warnings=["Something seems off"],
    )
    assert result.is_valid is False
    assert result.accepted_delta.flags == {"met_mara": True}
    assert len(result.rejected_changes) == 1
    assert result.rejected_changes[0]["field"] == "inventory_add"
    assert result.warnings == ["Something seems off"]
    assert result.requires_repair is False

    # Defaults
    default = ValidationResult()
    assert default.is_valid is True
    assert default.rejected_changes == []


def test_session_log_entry():
    entry = SessionLogEntry(
        turn_number=3,
        timestamp="2024-01-15T10:30:00",
        user_input="look around",
        narration="You find a cracked medallion.",
        npc_dialogue=[
            DialogueLine(
                speaker_id="mara_bellkeeper",
                speaker_name="Mara",
                role="Bellkeeper",
                tone="surprised",
                text="Where did you find that?",
            )
        ],
        accepted_state_delta=StateDelta(
            inventory_add=["cracked_silver_medallion"],
            clues_add=["ash_symbol"],
        ),
        rejected_changes=[],
        validator_warnings=[],
        next_options=["Examine it", "Show Mara", "Keep it secret"],
    )
    assert entry.turn_number == 3
    assert entry.timestamp == "2024-01-15T10:30:00"
    assert entry.user_input == "look around"
    assert entry.narration == "You find a cracked medallion."
    assert len(entry.npc_dialogue) == 1
    assert entry.npc_dialogue[0].text == "Where did you find that?"
    assert entry.accepted_state_delta.inventory_add == ["cracked_silver_medallion"]
    assert entry.rejected_changes == []
    assert entry.validator_warnings == []
    assert entry.next_options == ["Examine it", "Show Mara", "Keep it secret"]


def test_api_response():
    response = APIResponse(
        success=True,
        data={"scenario_id": "tiny_fantasy_sample", "session_id": "sess_abc123"},
        error=None,
        message="Scenario loaded successfully.",
    )
    assert response.success is True
    assert response.data["scenario_id"] == "tiny_fantasy_sample"
    assert response.data["session_id"] == "sess_abc123"
    assert response.error is None
    assert response.message == "Scenario loaded successfully."

    err = APIResponse(success=False, error="Scenario not found")
    assert err.success is False
    assert err.error == "Scenario not found"
