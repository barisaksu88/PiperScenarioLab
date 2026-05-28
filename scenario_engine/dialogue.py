"""Dialogue manager — validate, enrich, and format NPC dialogue lines."""

from typing import Any, Dict, List

from scenario_engine.models import DialogueLine, NPC, Scenario


class DialogueManager:
    """Process and format NPC dialogue output.

    Responsibilities:
        - Validate speaker_ids against the scenario's NPC registry
        - Fill in missing speaker_name / role from NPC data
        - Filter out dialogue from unavailable or dead NPCs
        - Format dialogue for UI display or LLM prompt context
    """

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def process_dialogue(
        self,
        dialogue_lines: List[DialogueLine],
        scenario: Scenario,
    ) -> List[DialogueLine]:
        """Validate and enrich dialogue lines.

        For each line:
            1. Validate that speaker_id exists in scenario.npcs
            2. Fill in speaker_name and role from NPC data if missing/empty
            3. Filter out lines from NPCs with status "dead" or "unavailable"

        Args:
            dialogue_lines: Raw dialogue lines from a TurnProposal.
            scenario: The current scenario (contains NPC registry).

        Returns:
            Enriched list of valid DialogueLine objects.
        """
        if not dialogue_lines:
            return []

        excluded_statuses = {"dead", "unavailable"}
        enriched: list[DialogueLine] = []

        for line in dialogue_lines:
            # Step 1: speaker_id must exist in scenario.npcs
            npc = scenario.npcs.get(line.speaker_id)
            if npc is None:
                continue  # skip unknown speakers

            # Step 2: filter out dead/unavailable NPCs
            if npc.status in excluded_statuses:
                continue

            # Step 3: fill in missing fields from NPC data
            speaker_name = line.speaker_name
            if not speaker_name:
                speaker_name = npc.name

            role = line.role
            if not role:
                role = npc.role

            enriched_line = DialogueLine(
                speaker_id=line.speaker_id,
                speaker_name=speaker_name,
                role=role,
                tone=line.tone,
                text=line.text,
            )
            enriched.append(enriched_line)

        return enriched

    def format_for_display(
        self,
        dialogue_lines: List[DialogueLine],
    ) -> List[Dict[str, Any]]:
        """Format dialogue lines for UI display.

        Returns a list of flat dicts with speaker, role, tone, and text
        keys suitable for JSON serialization to the frontend.

        Args:
            dialogue_lines: Validated/enriched dialogue lines.

        Returns:
            List of display dicts.
        """
        result: list[Dict[str, Any]] = []
        for line in dialogue_lines:
            result.append(
                {
                    "speaker": line.speaker_name,
                    "role": line.role,
                    "tone": line.tone,
                    "text": line.text,
                }
            )
        return result

    def format_for_prompt(
        self,
        dialogue_lines: List[DialogueLine],
    ) -> str:
        """Format recent dialogue for inclusion in an LLM prompt.

        Produces a compact "Speaker: text" representation that can be
        appended to the prompt context so the model knows what has
        recently been said.

        Args:
            dialogue_lines: Validated/enriched dialogue lines.

        Returns:
            Multi-line string of recent dialogue.
        """
        if not dialogue_lines:
            return ""

        entries: list[str] = []
        for line in dialogue_lines:
            speaker_label = line.speaker_name
            if line.role:
                speaker_label = f"{line.speaker_name} ({line.role})"
            entries.append(f"{speaker_label}: {line.text}")

        return "\n".join(entries)
