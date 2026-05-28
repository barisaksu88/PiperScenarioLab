"""Main scenario engine for PiperScenarioLab."""

from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scenario_engine.actor_selector import ActorSelector
from scenario_engine.dialogue import DialogueManager
from scenario_engine.llm_client import LLMClient
from scenario_engine.models import (
    Act,
    NPC,
    Scene,
    Scenario,
    SessionLogEntry,
    SessionStateResponse,
    StateDelta,
    TurnInput,
    TurnProposal,
    TurnResult,
    ValidationResult,
)
from scenario_engine.repair import Repair
from scenario_engine.storage import Storage
from scenario_engine.validator import Validator

LOG = logging.getLogger(__name__)


def _debug_enabled() -> bool:
    return os.environ.get("SCENARIO_DEBUG_LLM", "").strip() == "1"


class ScenarioEngine:
    """Main scenario engine coordinating the full turn cycle."""

    def __init__(
        self,
        storage: Storage,
        llm_client: LLMClient,
        session_id: Optional[str] = None,
    ):
        self.storage = storage
        self.llm_client = llm_client
        self.session_id = session_id or storage.generate_session_id()
        self.scenario: Optional[Scenario] = None
        self.validator: Optional[Validator] = None
        self.actor_selector: Optional[ActorSelector] = None
        self.dialogue_manager = DialogueManager()
        self.repair = Repair(llm_client)
        self.turn_number: int = 0

    async def load_scenario(self, scenario_id: str) -> None:
        """Load a scenario definition and initialize session.

        Loads the scenario from storage, creates the validator and actor
        selector, and persists the initial session state.
        """
        self.scenario = self.storage.load_scenario(scenario_id)
        self.validator = Validator(self.scenario, profile=None)
        self.actor_selector = ActorSelector(self.scenario)
        self.turn_number = 0

        initial_state = self._build_session_state_dict()
        self.storage.save_session(self.session_id, initial_state)

    async def new_scenario(self, scenario_id: str) -> None:
        """Start a new session with the given scenario.

        Resets turn_number to zero and delegates to load_scenario.
        """
        self.turn_number = 0
        self.session_id = self.storage.generate_session_id()
        await self.load_scenario(scenario_id)

    async def take_turn(self, turn_input: TurnInput) -> TurnResult:
        """Execute one full turn cycle.

        Steps:
        1. Increment turn number.
        2. Get current state.
        3. Select relevant NPCs.
        4. Build the LLM prompt.
        5. Generate TurnProposal from LLM.
        6. Validate the proposal.
        7. Apply accepted state delta.
        8. Process and enrich dialogue lines.
        9. Build TurnResult.
        10. Log entry to storage.
        11. Save session state.
        12. Return TurnResult.
        """
        if self.scenario is None:
            raise RuntimeError("No scenario loaded. Call load_scenario() first.")

        self.turn_number += 1

        # Step 2: Get current state
        current_state = self.get_state()

        # Step 3: Select relevant NPCs
        current_scene_id = self.scenario.player.current_scene
        selected_npcs = self.actor_selector.select_actors(
            turn_input.user_input, current_scene_id
        )
        if _debug_enabled():
            LOG.debug(
                "selected actors turn=%s scene=%s actors=%s",
                self.turn_number,
                current_scene_id,
                [npc.id for npc in selected_npcs],
            )

        # Step 4: Build LLM prompt
        prompt = self._build_turn_prompt(turn_input, selected_npcs)
        if _debug_enabled():
            LOG.debug("prompt length turn=%s chars=%s", self.turn_number, len(prompt))

        # Step 5: Generate TurnProposal
        context = {
            "turn_number": self.turn_number,
            "user_input": turn_input.user_input,
            "session_id": self.session_id,
        }
        try:
            raw_proposal = await self.llm_client.generate_turn(
                prompt, self.scenario, context
            )
        except Exception as e:
            LOG.warning("LLM turn generation failed; falling back to repair/minimal fallback: %s", e)
            raw_proposal = await self.repair.repair_turn_proposal(
                str(e), str(e), context
            )
            if raw_proposal is None:
                raw_proposal = self.repair.minimal_fallback(context)
        if _debug_enabled():
            LOG.debug("parsed proposal turn=%s payload=%s", self.turn_number, raw_proposal.model_dump(mode="json"))

        # Step 6: Validate the proposal
        validation = self.validator.validate_turn(raw_proposal)
        if _debug_enabled() and validation.rejected_changes:
            LOG.debug("validator rejected changes turn=%s changes=%s", self.turn_number, validation.rejected_changes)

        # Step 7: Apply accepted state delta
        self._apply_state_delta(validation.accepted_delta)

        # Step 8: Process dialogue
        dialogue = self.dialogue_manager.process_dialogue(
            raw_proposal.npc_dialogue, self.scenario
        )

        # Step 9: Build TurnResult
        now = datetime.now(timezone.utc).isoformat()
        turn_result = TurnResult(
            turn_number=self.turn_number,
            narration=raw_proposal.narration,
            npc_dialogue=dialogue,
            state_delta=validation.accepted_delta,
            validation=validation,
            next_options=raw_proposal.next_options,
            player_state=self.scenario.player.model_copy(deep=True),
            active_npcs=self._get_active_npcs(),
            current_act=self.scenario.player.current_act,
            current_scene=self._get_current_scene(),
            timestamp=now,
        )

        # Step 10: Log entry to storage
        log_entry = SessionLogEntry(
            turn_number=self.turn_number,
            timestamp=now,
            user_input=turn_input.user_input,
            narration=raw_proposal.narration,
            npc_dialogue=dialogue,
            accepted_state_delta=validation.accepted_delta,
            rejected_changes=validation.rejected_changes,
            validator_warnings=validation.warnings,
            next_options=raw_proposal.next_options,
        )
        self.storage.append_log_entry(self.session_id, log_entry)

        # Step 11: Save session state
        session_state = self._build_session_state_dict()
        self.storage.save_session(self.session_id, session_state)

        return turn_result

    async def reset(self) -> None:
        """Reset to initial scenario state.

        Reloads the scenario definition from storage and resets turn_number
        to zero, effectively restarting the session.
        """
        if self.scenario is None:
            raise RuntimeError("No scenario loaded. Cannot reset.")
        scenario_id = None
        for key in self.storage.list_scenarios():
            if key["title"] == self.scenario.metadata.title:
                scenario_id = key["id"]
                break

        # Fallback: try to find by matching acts/npcs signature
        if scenario_id is None:
            saved_session = self.storage.load_session(self.session_id)
            if saved_session and "scenario_id" in saved_session:
                scenario_id = saved_session["scenario_id"]

        if scenario_id is None:
            raise RuntimeError("Cannot determine scenario_id for reset.")

        self.turn_number = 0
        self.scenario = self.storage.load_scenario(scenario_id)
        self.validator = Validator(self.scenario, profile=None)
        self.actor_selector = ActorSelector(self.scenario)

        initial_state = self._build_session_state_dict()
        self.storage.save_session(self.session_id, initial_state)

    def get_state(self) -> SessionStateResponse:
        """Return current session state for UI."""
        if self.scenario is None:
            return SessionStateResponse(turn_number=self.turn_number)

        inventory_items = [
            self.scenario.items[item_id]
            for item_id in self.scenario.player.inventory
            if item_id in self.scenario.items
        ]
        skills = [
            self.scenario.skills[skill_id]
            for skill_id in self.scenario.player.skills
            if skill_id in self.scenario.skills
        ]

        objectives: List[Any] = []
        for act in self.scenario.acts.values():
            for obj in act.objectives.values():
                objectives.append(obj)

        return SessionStateResponse(
            scenario=self.scenario.metadata,
            player=self.scenario.player.model_copy(deep=True),
            current_act=self.scenario.player.current_act,
            current_scene=self._get_current_scene(),
            active_npcs=self._get_active_npcs(),
            objectives=objectives,
            inventory_items=inventory_items,
            skills=skills,
            flags=dict(self.scenario.player.flags),
            turn_number=self.turn_number,
        )

    def get_session_log(self) -> List[SessionLogEntry]:
        """Return full session log."""
        return self.storage.load_session_log(self.session_id)

    def _build_turn_prompt(
        self, turn_input: TurnInput, selected_npcs: List[NPC]
    ) -> str:
        """Build the narrator turn prompt from templates and current state.

        Loads the narrator_turn.txt prompt template and replaces placeholders
        with current scenario state.
        """
        if self.scenario is None:
            return turn_input.user_input

        # Try to load the profile's prompt template
        template_path = None
        prompt_template_dir = self.scenario.profile.prompt_template_dir
        if prompt_template_dir:
            candidate = os.path.join(prompt_template_dir, "narrator_turn.txt")
            if os.path.exists(candidate):
                template_path = candidate

        if template_path:
            template = open(template_path, encoding="utf-8").read()
        else:
            template = self._default_turn_prompt_template()

        # Get current act and scene info
        current_act = self._get_current_act()
        current_scene = self._get_current_scene()

        act_name = current_act.name if current_act else "Unknown"
        scene_name = current_scene.name if current_scene else "Unknown"
        scene_description = current_scene.description if current_scene else ""

        # Build NPC persona block
        npc_personas = ""
        if selected_npcs:
            lines = []
            for npc in selected_npcs:
                lines.append(f"- {npc.name} ({npc.role}): {npc.persona.temperament}")
                if npc.persona.speech_style:
                    lines.append(f"  Speech style: {npc.persona.speech_style}")
                if npc.persona.motives:
                    lines.append(f"  Motives: {', '.join(npc.persona.motives)}")
                if npc.knows:
                    lines.append(f"  Knows: {', '.join(npc.knows)}")
            npc_personas = "\n".join(lines)
        else:
            npc_personas = "(No NPCs present)"

        # Build inventory list
        def _item_name(iid: str) -> str:
            item = self.scenario.items.get(iid, None)
            return item.name if item is not None else iid

        inventory_list = ", ".join(
            _item_name(iid) for iid in self.scenario.player.inventory
        ) or "(empty)"

        # Build clues list
        clues_list = ", ".join(self.scenario.player.clues) or "(none)"

        # Build flags string
        flags_str = json.dumps(self.scenario.player.flags, indent=2) if self.scenario.player.flags else "{}"

        # Build recent log (last 5 turns)
        recent_log = ""
        try:
            log = self.storage.load_session_log(self.session_id)
            recent_entries = log[-5:]
            lines = []
            for entry in recent_entries:
                lines.append(f"Turn {entry.turn_number}: {entry.user_input}")
                lines.append(f"  -> {entry.narration[:200]}...")
            recent_log = "\n".join(lines) if lines else "(No previous turns)"
        except Exception:
            recent_log = "(Log unavailable)"

        # Replace placeholders
        prompt = template
        replacements = {
            "{scenario_title}": self.scenario.metadata.title,
            "{current_act}": act_name,
            "{current_scene}": scene_name,
            "{scene_description}": scene_description,
            "{npc_personas}": npc_personas,
            "{inventory_list}": inventory_list,
            "{clues_list}": clues_list,
            "{flags}": flags_str,
            "{recent_log}": recent_log,
            "{user_input}": turn_input.user_input,
        }
        for placeholder, value in replacements.items():
            prompt = prompt.replace(placeholder, value)

        return prompt

    def _default_turn_prompt_template(self) -> str:
        """Return a default prompt template if the profile template is missing."""
        return (
            "You are the narrator for a roleplay scenario.\n\n"
            "Scenario: {scenario_title}\n"
            "Act: {current_act}\n"
            "Scene: {current_scene}\n"
            "Description: {scene_description}\n\n"
            "NPCs present:\n{npc_personas}\n\n"
            "Player inventory: {inventory_list}\n"
            "Player clues: {clues_list}\n"
            "Player flags: {flags}\n\n"
            "Recent history:\n{recent_log}\n\n"
            "Player input: {user_input}\n\n"
            "Respond with valid JSON matching the TurnProposal schema:\n"
            "- narration: string describing what happens\n"
            "- npc_dialogue: list of dialogue lines (speaker_id, speaker_name, text, tone)\n"
            "- state_delta: changes to apply (flags, inventory_add, clues_add, etc.)\n"
            "- next_options: 2-4 suggested player actions\n\n"
            "Anti-drift rules:\n"
            "- Stay consistent with established scene descriptions and NPC personas.\n"
            "- Do not introduce new locations, characters, or items not in the scenario.\n"
            "- Keep the narrative tone consistent with the scenario genre.\n"
            "- Dialogue must match each NPC's speech style and temperament.\n"
        )

    def _apply_state_delta(self, delta: StateDelta) -> None:
        """Apply validated state delta to current scenario state.

        Handles flags, inventory, clues, skills, relationships,
        scene moves, objective completion/failure, and NPC status changes.
        """
        if self.scenario is None:
            return

        # Merge flags
        for key, value in delta.flags.items():
            self.scenario.player.flags[key] = value

        # Add inventory items (avoid duplicates)
        for item_id in delta.inventory_add:
            if item_id not in self.scenario.player.inventory:
                self.scenario.player.inventory.append(item_id)

        # Remove inventory items
        for item_id in delta.inventory_remove:
            if item_id in self.scenario.player.inventory:
                self.scenario.player.inventory.remove(item_id)

        # Add clues (avoid duplicates)
        for clue_id in delta.clues_add:
            if clue_id not in self.scenario.player.clues:
                self.scenario.player.clues.append(clue_id)

        # Add skills (avoid duplicates)
        for skill_id in delta.skills_add:
            if skill_id not in self.scenario.player.skills:
                self.scenario.player.skills.append(skill_id)

        # Apply relationship changes
        for change in delta.relationship_changes:
            npc_id = change.get("npc_id", "")
            if npc_id in self.scenario.npcs:
                rel = self.scenario.npcs[npc_id].relationship_to_player
                for rel_key in ["trust", "fear", "hostility", "respect"]:
                    if rel_key in change:
                        current_val = getattr(rel, rel_key, 0)
                        new_val = current_val + change[rel_key]
                        setattr(rel, rel_key, max(-100, min(100, new_val)))

        # Move player to scene
        if delta.move_player_to_scene is not None:
            self.scenario.player.current_scene = delta.move_player_to_scene

        # Move NPCs to scenes
        for move in delta.move_npc_to_scene:
            npc_id = move.get("npc_id", "")
            scene_id = move.get("scene_id", "")
            if npc_id in self.scenario.npcs:
                self.scenario.npcs[npc_id].current_scene = scene_id

        # Complete objectives
        for obj_id in delta.complete_objectives:
            for act in self.scenario.acts.values():
                if obj_id in act.objectives:
                    act.objectives[obj_id].status = "complete"

        # Fail objectives
        for obj_id in delta.fail_objectives:
            for act in self.scenario.acts.values():
                if obj_id in act.objectives:
                    act.objectives[obj_id].status = "failed"

        # NPC status changes
        for npc_id, status in delta.npc_status_changes.items():
            if npc_id in self.scenario.npcs:
                self.scenario.npcs[npc_id].status = status

    def _get_current_act(self) -> Optional[Act]:
        """Get the current act from player state."""
        if self.scenario is None:
            return None
        return self.scenario.acts.get(self.scenario.player.current_act, None)

    def _get_current_scene(self) -> Optional[Scene]:
        """Get the current scene from player state."""
        act = self._get_current_act()
        if act is None:
            return None
        return act.scenes.get(self.scenario.player.current_scene, None)

    def _get_active_npcs(self) -> List[NPC]:
        """Get NPCs in the current scene with available status."""
        if self.scenario is None:
            return []

        current_scene_id = self.scenario.player.current_scene
        active: List[NPC] = []

        for npc in self.scenario.npcs.values():
            if npc.status not in ("available",):
                continue
            if npc.current_scene == current_scene_id:
                active.append(npc)

        return active

    def _build_session_state_dict(self) -> Dict[str, Any]:
        """Build a serializable dict of the current session state for storage."""
        if self.scenario is None:
            return {
                "session_id": self.session_id,
                "turn_number": self.turn_number,
                "scenario_id": None,
            }

        # Find the scenario_id by matching title against known scenarios
        scenario_id = None
        for info in self.storage.list_scenarios():
            if info["title"] == self.scenario.metadata.title:
                scenario_id = info["id"]
                break

        return {
            "session_id": self.session_id,
            "turn_number": self.turn_number,
            "scenario_id": scenario_id,
            "scenario": self.scenario.model_dump(mode="json"),
        }
