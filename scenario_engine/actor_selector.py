"""Actor selector — choose relevant NPCs for the current turn."""

from typing import List

from scenario_engine.models import NPC, Scenario


class ActorSelector:
    """Select relevant NPCs/actors for the current turn.

    Selection is purely rule-based (no LLM calls):
        1. NPCs physically present in the current scene
        2. NPCs mentioned by name in the user's input
        3. NPCs whose trigger conditions match current flags
    """

    def __init__(self, scenario: Scenario):
        self.scenario = scenario

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def select_actors(self, user_input: str, current_scene_id: str) -> List[NPC]:
        """Return a deduplicated, filtered list of NPCs relevant to this turn.

        Args:
            user_input: The player's free-text input or selected option.
            current_scene_id: The scene the player is currently in.

        Returns:
            List of active NPC objects relevant to the turn.
        """
        selected: dict[str, NPC] = {}

        # 1. NPCs in the current scene
        for npc in self._npcs_in_scene(current_scene_id):
            selected[npc.id] = npc

        # 2. NPCs mentioned by name in user_input
        for npc in self._npcs_mentioned(user_input):
            selected[npc.id] = npc

        # 3. NPCs with trigger conditions matching current flags
        for npc in self._npcs_with_matching_triggers():
            selected[npc.id] = npc

        # 4. Filter out dead or unavailable NPCs
        return self._filter_active(selected.values())

    def build_persona_prompt(self, npcs: List[NPC]) -> str:
        """Build a persona card text block for the given NPCs.

        The output is meant to be embedded directly into an LLM prompt
        so the model knows who is present and how they speak.

        Args:
            npcs: List of NPCs to include in the persona text.

        Returns:
            Multi-line string with one stanza per NPC.
        """
        if not npcs:
            return "(No NPCs are present.)"

        lines: list[str] = []
        lines.append("--- NPC PERSONAS ---")
        for npc in npcs:
            persona_parts: list[str] = []

            persona_parts.append(
                f"{npc.name} ({npc.role}): {npc.persona.speech_style}"
            )

            if npc.persona.motives:
                persona_parts.append(
                    "Motives: " + ", ".join(npc.persona.motives)
                )
            if npc.persona.fears:
                persona_parts.append(
                    "Fears: " + ", ".join(npc.persona.fears)
                )
            if npc.knows:
                persona_parts.append("Knows: " + ", ".join(npc.knows))
            if npc.can_reveal:
                persona_parts.append(
                    "Can reveal: " + ", ".join(npc.can_reveal)
                )

            lines.append("\n".join(persona_parts))

        lines.append("--- END NPC PERSONAS ---")
        return "\n\n".join(lines)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _npcs_in_scene(self, scene_id: str) -> List[NPC]:
        """Return NPCs whose current_scene matches *scene_id*."""
        result: list[NPC] = []
        for npc in self.scenario.npcs.values():
            if npc.current_scene == scene_id:
                result.append(npc)
        return result

    def _npcs_mentioned(self, user_input: str) -> List[NPC]:
        """Return NPCs whose name appears (case-insensitive) in *user_input*."""
        if not user_input:
            return []

        lower_input = user_input.lower()
        result: list[NPC] = []
        for npc in self.scenario.npcs.values():
            if npc.name and npc.name.lower() in lower_input:
                result.append(npc)
            elif npc.id and npc.id.lower() in lower_input:
                result.append(npc)
        return result

    def _npcs_with_matching_triggers(self) -> List[NPC]:
        """Return NPCs whose trigger condition matches any active flag."""
        flags = self.scenario.player.flags if self.scenario.player else {}
        global_flags = self.scenario.global_flags

        result: list[NPC] = []
        for npc in self.scenario.npcs.values():
            for trigger in npc.triggers:
                condition = trigger.condition.lower().strip()
                if self._condition_matches_flags(
                    condition, flags, global_flags
                ):
                    result.append(npc)
                    break  # one match per NPC is enough
        return result

    def _condition_matches_flags(
        self,
        condition: str,
        flags: dict,
        global_flags: dict,
    ) -> bool:
        """Check if a trigger condition string matches any active flag.

        Supports simple exact matches and 'flag_name=true/false' style.
        """
        if not condition:
            return False

        # Handle "flag=value" format
        if "=" in condition:
            parts = condition.split("=", 1)
            flag_name = parts[0].strip()
            expected_value = parts[1].strip()

            all_flags = {**global_flags, **flags}
            actual_value = all_flags.get(flag_name)

            if actual_value is None:
                return False

            # Compare as strings for simplicity
            return str(actual_value).lower() == expected_value.lower()

        # Simple presence check: if the condition string appears as a
        # flag key (case-insensitive), it's a match.
        all_flag_keys = list(flags.keys()) + list(global_flags.keys())
        for key in all_flag_keys:
            if condition == key.lower():
                return True

        return False

    def _filter_active(self, npcs) -> List[NPC]:
        """Remove NPCs whose status is 'dead' or 'unavailable'."""
        excluded = {"dead", "unavailable"}
        result: list[NPC] = []
        for npc in npcs:
            if npc.status not in excluded:
                result.append(npc)
        return result
