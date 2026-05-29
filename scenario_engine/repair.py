"""Handle repair of invalid LLM outputs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from .llm_client import LLMClient
from .models import StateDelta, TurnProposal

LOG = logging.getLogger(__name__)


class Repair:
    """Handle repair of invalid LLM outputs."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    @staticmethod
    def extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Extract a JSON object from raw model output."""
        if text is None:
            return None
        text = str(text).strip()
        if not text:
            return None

        fenced_patterns = (
            r"```json\s*(\{.*?\})\s*```",
            r"```\s*(\{.*?\})\s*```",
        )
        for pattern in fenced_patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def clean_narration(text: str) -> str:
        """Scrub LLM artifacts from narration text after JSON parsing.

        Removes markdown fences, stray JSON keys, and common meta-text
        that the LLM sometimes embeds inside the narration string.
        """
        if not text:
            return text
        # Strip markdown fences
        text = text.replace("```json", "").replace("```", "")
        # Remove common stray JSON key prefixes that LLMs insert
        artifacts = (
            r'"npc_dialogue"\s*:\s*\[.*?\]',
            r'"state_delta"\s*:\s*\{.*?\}',
            r'"next_options"\s*:\s*\[.*?\]',
            r'"narration"\s*:\s*"',
        )
        for pattern in artifacts:
            text = re.sub(pattern, "", text, flags=re.DOTALL)
        # Remove remaining stray braces and brackets that may be left over
        text = text.replace("{", "").replace("}", "")
        # Collapse multiple spaces/newlines
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    async def parse_turn_output(self, broken: str, context: Dict[str, Any]) -> TurnProposal:
        """Parse model text into a TurnProposal, repairing once if needed."""
        extracted = self.extract_json(broken)
        if extracted is not None:
            try:
                proposal = TurnProposal.model_validate(extracted)
                # Scrub any LLM artifacts that leaked into the narration field
                if proposal.narration:
                    proposal.narration = self.clean_narration(proposal.narration)
                return proposal
            except Exception:
                LOG.debug("initial extraction produced invalid TurnProposal", exc_info=True)

        repaired = await self.llm_client.repair_json(
            broken,
            schema_hint=(
                "TurnProposal schema: {narration: string, npc_dialogue: Array<{speaker_id, speaker_name, role, tone, text}>, "
                "state_delta: {flags, inventory_add, inventory_remove, clues_add, skills_add, used_skills, relationship_changes, "
                "move_player_to_scene, move_npc_to_scene, complete_objectives, fail_objectives, npc_status_changes}, "
                "next_options: string[]}"
            ),
        )
        if repaired is not None:
            try:
                return TurnProposal.model_validate(repaired)
            except Exception:
                LOG.debug("repair_json result was invalid TurnProposal", exc_info=True)

        return self._text_fallback(broken, context)

    async def repair_turn_proposal(self, broken: str, error: str, context: Dict[str, Any]) -> Optional[TurnProposal]:
        """Backward-compatible repair entrypoint."""
        del error
        return await self.parse_turn_output(broken, context)

    def _text_fallback(self, broken: str, context: Dict[str, Any]) -> TurnProposal:
        """Use the raw model text as narration when JSON parsing fails completely."""
        text = (broken or "").strip()
        # If the text is empty or just whitespace, use the minimal fallback
        if not text:
            return self.minimal_fallback(context)
        # Clean up common LLM artifacts
        text = text.replace("```json", "").replace("```", "").strip()
        # If after cleanup there's still substantial text, use it
        if len(text) > 20:
            return TurnProposal(
                narration=text,
                npc_dialogue=[],
                state_delta=StateDelta(),
                next_options=[
                    "Look around carefully.",
                    "Wait and observe.",
                    "Try a different approach.",
                ],
            )
        return self.minimal_fallback(context)

    def minimal_fallback(self, context: Dict[str, Any]) -> TurnProposal:
        """Return a minimal valid TurnProposal when all repair fails."""
        del context
        return TurnProposal(
            narration="Time passes. The world around you remains still as you contemplate your next move.",
            npc_dialogue=[],
            state_delta=StateDelta(),
            next_options=[
                "Look around carefully.",
                "Wait and observe.",
                "Try a different approach.",
            ],
        )
