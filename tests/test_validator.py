import pytest
from scenario_engine.models import *
from scenario_engine.validator import Validator


@pytest.fixture
def fantasy_scenario():
    from pathlib import Path
    import json

    path = Path("scenarios") / "tiny_fantasy_sample.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Scenario.model_validate(raw)


def test_validator_accepts_empty_delta(fantasy_scenario):
    """Empty StateDelta should pass."""
    validator = Validator(fantasy_scenario)
    proposal = TurnProposal(narration="Nothing happens.")
    result = validator.validate_turn(proposal)
    assert result.is_valid is True
    assert result.rejected_changes == []


def test_validator_rejects_nonexistent_item(fantasy_scenario):
    """delta with inventory_add=['nonexistent_sword'] should be rejected."""
    validator = Validator(fantasy_scenario)
    delta = StateDelta(inventory_add=["nonexistent_sword"])
    proposal = TurnProposal(state_delta=delta)
    result = validator.validate_turn(proposal)
    assert len(result.rejected_changes) >= 1
    rejected_fields = [rc["field"] for rc in result.rejected_changes]
    assert "inventory_add" in rejected_fields
    assert result.accepted_delta.inventory_add == []


def test_validator_rejects_nonexistent_scene(fantasy_scenario):
    """delta with move_player_to_scene='nonexistent_place' should be rejected."""
    validator = Validator(fantasy_scenario)
    delta = StateDelta(move_player_to_scene="nonexistent_place")
    proposal = TurnProposal(state_delta=delta)
    result = validator.validate_turn(proposal)
    rejected_fields = [rc["field"] for rc in result.rejected_changes]
    assert "move_player_to_scene" in rejected_fields
    assert result.accepted_delta.move_player_to_scene is None


def test_validator_rejects_unknown_skill(fantasy_scenario):
    """delta with skills_add=['unknown_magic'] should be rejected."""
    validator = Validator(fantasy_scenario)
    delta = StateDelta(skills_add=["unknown_magic"])
    proposal = TurnProposal(state_delta=delta)
    result = validator.validate_turn(proposal)
    rejected_fields = [rc["field"] for rc in result.rejected_changes]
    assert "skills_add" in rejected_fields
    assert result.accepted_delta.skills_add == []


def test_validator_clamps_relationship(fantasy_scenario):
    """delta with relationship change trust=999 should be clamped to 100."""
    validator = Validator(fantasy_scenario)
    delta = StateDelta(
        relationship_changes=[{"npc_id": "mara_bellkeeper", "trust": 999}]
    )
    proposal = TurnProposal(state_delta=delta)
    result = validator.validate_turn(proposal)
    assert len(result.accepted_delta.relationship_changes) == 1
    assert result.accepted_delta.relationship_changes[0]["trust"] == 100


def test_validator_accepts_valid_flag(fantasy_scenario):
    """delta with flags={'met_mara': True} should be accepted (profile allows dynamic flags)."""
    validator = Validator(fantasy_scenario)
    delta = StateDelta(flags={"met_mara": True})
    proposal = TurnProposal(state_delta=delta)
    result = validator.validate_turn(proposal)
    assert result.accepted_delta.flags == {"met_mara": True}
    flag_rejected = any(rc["field"] == "flags" for rc in result.rejected_changes)
    assert not flag_rejected


def test_validator_rejects_clue_not_in_scene(fantasy_scenario):
    """delta with clues_add=['impossible_clue'] should be rejected."""
    validator = Validator(fantasy_scenario)
    delta = StateDelta(clues_add=["impossible_clue"])
    proposal = TurnProposal(state_delta=delta)
    result = validator.validate_turn(proposal)
    rejected_fields = [rc["field"] for rc in result.rejected_changes]
    assert "clues_add" in rejected_fields
    assert result.accepted_delta.clues_add == []


def test_validator_accepts_legal_inventory_add(fantasy_scenario):
    """adding 'cracked_silver_medallion' if it exists in scenario."""
    validator = Validator(fantasy_scenario)
    delta = StateDelta(inventory_add=["cracked_silver_medallion"])
    proposal = TurnProposal(state_delta=delta)
    result = validator.validate_turn(proposal)
    assert "cracked_silver_medallion" in result.accepted_delta.inventory_add
    inventory_rejected = [
        rc for rc in result.rejected_changes if rc["field"] == "inventory_add"
    ]
    assert inventory_rejected == []


def test_validator_partial_accept(fantasy_scenario):
    """Mix of valid and invalid changes -- valid accepted, invalid rejected."""
    validator = Validator(fantasy_scenario)
    delta = StateDelta(
        inventory_add=["cracked_silver_medallion", "nonexistent_item"],
        flags={"met_mara": True},
        skills_add=["perception", "forbidden_magic"],
    )
    proposal = TurnProposal(state_delta=delta)
    result = validator.validate_turn(proposal)

    # Valid parts accepted
    assert "cracked_silver_medallion" in result.accepted_delta.inventory_add
    assert result.accepted_delta.flags == {"met_mara": True}
    assert "perception" in result.accepted_delta.skills_add

    # Invalid parts rejected
    rejected_inventory = [
        rc["value"] for rc in result.rejected_changes if rc["field"] == "inventory_add"
    ]
    assert "nonexistent_item" in rejected_inventory

    rejected_skills = [
        rc["value"] for rc in result.rejected_changes if rc["field"] == "skills_add"
    ]
    assert "forbidden_magic" in rejected_skills


def test_validator_npc_status_change(fantasy_scenario):
    """Valid status change for existing NPC accepted, nonexistent NPC rejected."""
    validator = Validator(fantasy_scenario)
    delta = StateDelta(
        npc_status_changes={
            "mara_bellkeeper": "unavailable",
            "ghost_npc": "dead",
        }
    )
    proposal = TurnProposal(state_delta=delta)
    result = validator.validate_turn(proposal)

    # Valid: existing NPC
    assert (
        result.accepted_delta.npc_status_changes.get("mara_bellkeeper")
        == "unavailable"
    )

    # Invalid: nonexistent NPC should be rejected
    assert "ghost_npc" not in result.accepted_delta.npc_status_changes
    rejected_npc = [
        rc for rc in result.rejected_changes if rc["field"] == "npc_status_changes"
    ]
    assert len(rejected_npc) >= 1


def test_validator_rejects_illegal_llm_proposal(fantasy_scenario):
    """A model proposal with multiple impossible changes should only accept legal ones."""
    validator = Validator(fantasy_scenario)
    proposal = TurnProposal(
        narration="The model tries to invent things.",
        state_delta=StateDelta(
            inventory_add=["cracked_silver_medallion", "imaginary_amulet"],
            move_player_to_scene="nonexistent_scene",
            skills_add=["perception", "telepathy"],
            clues_add=["impossible_clue"],
            relationship_changes=[{"npc_id": "mara_bellkeeper", "trust": 7}],
        ),
    )
    result = validator.validate_turn(proposal)

    assert "cracked_silver_medallion" in result.accepted_delta.inventory_add
    assert "perception" in result.accepted_delta.skills_add
    assert result.accepted_delta.move_player_to_scene is None
    assert result.accepted_delta.clues_add == []
    assert any(change["value"] == "imaginary_amulet" for change in result.rejected_changes)
    assert any(change["value"] == "nonexistent_scene" for change in result.rejected_changes)
