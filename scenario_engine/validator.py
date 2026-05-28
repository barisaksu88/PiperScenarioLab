"""Validator for turn proposals and state deltas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from scenario_engine.models import (
    NPC,
    Act,
    Scene,
    Scenario,
    StateDelta,
    TurnProposal,
    ValidationResult,
)
from scenario_engine.debug import get_current_debug_run_dir, write_jsonl


class Validator:
    """Validate a TurnProposal's state_delta against scenario rules."""

    def __init__(self, scenario: Scenario, profile: Any = None):
        self.scenario = scenario
        self.profile = profile

    def validate_turn(self, proposal: TurnProposal) -> ValidationResult:
        """Validate a TurnProposal's state_delta against scenario rules.

        Returns a ValidationResult with accepted/rejected changes and warnings.
        """
        result = ValidationResult(is_valid=True)
        delta = proposal.state_delta

        self._validate_inventory_changes(delta, result)
        self._validate_scene_move(delta, result)
        self._validate_clue_reveal(delta, result)
        self._validate_objective_completion(delta, result)
        self._validate_relationship_bounds(delta, result)
        self._validate_skill_grants(delta, result)
        self._validate_npc_status(delta, result)
        self._validate_act_progression(delta, result)

        if result.rejected_changes:
            result.warnings.insert(0, f"Rejected {len(result.rejected_changes)} invalid change(s).")
        run_dir = get_current_debug_run_dir()
        if run_dir is not None and result.rejected_changes:
            write_jsonl(run_dir / "validator_debug.jsonl", {
                "rejected_changes": result.rejected_changes,
                "warnings": result.warnings,
                "accepted_delta": result.accepted_delta.model_dump(mode="json"),
            })

        return result

    def _validate_inventory_changes(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject items not in scenario.items unless profile allows dynamic creation."""
        allows_dynamic = False
        if self.profile and hasattr(self.profile, "check_dynamic_creation_allowed"):
            allows_dynamic = self.profile.check_dynamic_creation_allowed("items")

        valid_items: List[str] = []
        for item_id in delta.inventory_add:
            if item_id in self.scenario.items or allows_dynamic:
                valid_items.append(item_id)
            else:
                result.rejected_changes.append(
                    {"field": "inventory_add", "value": item_id, "reason": "Item not defined in scenario"}
                )
        result.accepted_delta.inventory_add = valid_items

        valid_removes: List[str] = []
        for item_id in delta.inventory_remove:
            if item_id in self.scenario.player.inventory:
                valid_removes.append(item_id)
            else:
                result.rejected_changes.append(
                    {"field": "inventory_remove", "value": item_id, "reason": "Item not in player inventory"}
                )
        result.accepted_delta.inventory_remove = valid_removes

    def _validate_scene_move(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject moves to nonexistent or disconnected scenes."""
        if delta.move_player_to_scene is None:
            return

        target_scene_id = delta.move_player_to_scene
        current_scene = self._get_current_scene()

        if current_scene and target_scene_id == current_scene.id:
            result.accepted_delta.move_player_to_scene = target_scene_id
            return

        all_scenes: Dict[str, Scene] = {}
        for act in self.scenario.acts.values():
            all_scenes.update(act.scenes)

        if target_scene_id not in all_scenes:
            result.rejected_changes.append(
                {
                    "field": "move_player_to_scene",
                    "value": target_scene_id,
                    "reason": "Target scene does not exist",
                }
            )
            return

        if current_scene and target_scene_id not in current_scene.connected_scenes:
            result.rejected_changes.append(
                {
                    "field": "move_player_to_scene",
                    "value": target_scene_id,
                    "reason": "Target scene not connected to current scene",
                }
            )
            return

        result.accepted_delta.move_player_to_scene = target_scene_id

    def _validate_clue_reveal(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject clues not present in current scene or NPC can_reveal."""
        valid_clues: List[str] = []
        current_scene = self._get_current_scene()
        scene_clues = set(current_scene.clues_present) if current_scene else set()

        npc_can_reveal: set = set()
        for npc in self.scenario.npcs.values():
            if npc.current_scene == self.scenario.player.current_scene:
                npc_can_reveal.update(npc.can_reveal)

        for clue_id in delta.clues_add:
            if clue_id in scene_clues or clue_id in npc_can_reveal:
                valid_clues.append(clue_id)
            else:
                result.rejected_changes.append(
                    {"field": "clues_add", "value": clue_id, "reason": "Clue not in scene or NPC can_reveal"}
                )
        result.accepted_delta.clues_add = valid_clues

    def _validate_objective_completion(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject objective completion unless required flags/clues are met."""
        valid_completes: List[str] = []
        for obj_id in delta.complete_objectives:
            objective = None
            for act in self.scenario.acts.values():
                if obj_id in act.objectives:
                    objective = act.objectives[obj_id]
                    break

            if objective is None:
                result.rejected_changes.append(
                    {
                        "field": "complete_objectives",
                        "value": obj_id,
                        "reason": "Objective not found",
                    }
                )
                continue

            player_flags = self.scenario.player.flags
            player_clues = set(self.scenario.player.clues)
            flags_met = all(flag in player_flags for flag in objective.required_flags)
            clues_met = all(clue in player_clues for clue in objective.required_clues)

            if flags_met and clues_met:
                valid_completes.append(obj_id)
            else:
                result.rejected_changes.append(
                    {
                        "field": "complete_objectives",
                        "value": obj_id,
                        "reason": "Required flags or clues not met",
                    }
                )
        result.accepted_delta.complete_objectives = valid_completes

        valid_fails: List[str] = []
        for obj_id in delta.fail_objectives:
            found = any(obj_id in act.objectives for act in self.scenario.acts.values())
            if found:
                valid_fails.append(obj_id)
            else:
                result.rejected_changes.append(
                    {"field": "fail_objectives", "value": obj_id, "reason": "Objective not found"}
                )
        result.accepted_delta.fail_objectives = valid_fails

    def _validate_relationship_bounds(self, delta: StateDelta, result: ValidationResult) -> None:
        """Clamp relationship values to [-100, 100]."""
        valid_changes: List[Dict[str, Any]] = []
        for change in delta.relationship_changes:
            npc_id = change.get("npc_id", "")
            if npc_id not in self.scenario.npcs:
                result.rejected_changes.append(
                    {
                        "field": "relationship_changes",
                        "value": change,
                        "reason": f"NPC '{npc_id}' not found",
                    }
                )
                continue

            clamped = dict(change)
            for key in ["trust", "fear", "hostility", "respect"]:
                if key in clamped:
                    val = clamped[key]
                    if not isinstance(val, (int, float)):
                        continue
                    clamped[key] = max(-100, min(100, int(val)))
            valid_changes.append(clamped)
        result.accepted_delta.relationship_changes = valid_changes

    def _validate_skill_grants(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject skills not in scenario.skills unless profile allows dynamic creation."""
        allows_dynamic = False
        if self.profile and hasattr(self.profile, "check_dynamic_creation_allowed"):
            allows_dynamic = self.profile.check_dynamic_creation_allowed("skills")

        valid_skills: List[str] = []
        for skill_id in delta.skills_add:
            if skill_id in self.scenario.skills or allows_dynamic:
                valid_skills.append(skill_id)
            else:
                result.rejected_changes.append(
                    {"field": "skills_add", "value": skill_id, "reason": "Skill not defined in scenario"}
                )
        result.accepted_delta.skills_add = valid_skills

    def _validate_npc_status(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject status changes to nonexistent NPCs."""
        valid_status_changes: Dict[str, str] = {}
        for npc_id, status in delta.npc_status_changes.items():
            if npc_id in self.scenario.npcs:
                valid_status_changes[npc_id] = status
            else:
                result.rejected_changes.append(
                    {
                        "field": "npc_status_changes",
                        "value": {npc_id: status},
                        "reason": f"NPC '{npc_id}' not found",
                    }
                )
        result.accepted_delta.npc_status_changes = valid_status_changes

    def _validate_act_progression(self, delta: StateDelta, result: ValidationResult) -> None:
        """Accept act progression flags but log warnings for unexpected transitions."""
        for flag_key, flag_value in delta.flags.items():
            if flag_key.startswith("act_") and flag_key.endswith("_complete"):
                act_id = flag_key.replace("_complete", "")
                if act_id not in self.scenario.acts:
                    result.warnings.append(f"Flag references unknown act: {act_id}")
        result.accepted_delta.flags.update(delta.flags)

    def _get_current_scene(self) -> Optional[Scene]:
        """Get the current scene from player state."""
        act = self.scenario.acts.get(self.scenario.player.current_act, None)
        if act is None:
            return None
        return act.scenes.get(self.scenario.player.current_scene, None)
