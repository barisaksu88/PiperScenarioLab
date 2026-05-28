"""Handle repair of invalid LLM outputs."""

import json
import re
from typing import Any, Dict, Optional

from .models import DialogueLine, StateDelta, TurnProposal
from .llm_client import LLMClient


class Repair:
    """Handle repair of invalid LLM outputs."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def repair_turn_proposal(self, broken: str, error: str, context: Dict[str, Any]) -> Optional[TurnProposal]:
        """
        Attempt to repair an invalid TurnProposal.
        1. Try JSON extraction (find JSON block in text)
        2. Try schema repair prompt via LLM
        3. Fallback to minimal valid TurnProposal
        """
        # Step 1: Try JSON extraction
        extracted = self.extract_json(broken)
        if extracted:
            try:
                return TurnProposal.model_validate(extracted)
            except Exception:
                pass

        # Step 2: Try LLM repair
        try:
            schema_hint = (
                "TurnProposal schema: {narration: string, npc_dialogue: Array<{"
                "speaker_id, speaker_name, role, tone, text}>, state_delta: {"
                "flags, inventory_add, inventory_remove, clues_add, skills_add, "
                "relationship_changes, move_player_to_scene, move_npc_to_scene, "
                "complete_objectives, fail_objectives, npc_status_changes}, "
                "next_options: string[]}"
            )
            repaired = await self.llm_client.repair_json(broken, schema_hint)
            if repaired:
                return TurnProposal.model_validate(repaired)
        except Exception:
            pass

        # Step 3: Fallback
        return self.minimal_fallback(context)

    def extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON object from text that may contain markdown or extra content."""
        if text is None:
            return None
        text = str(text).strip()
        if not text:
            return None
        # Try to find JSON block in markdown
        patterns = [
            r"```json\s*\n(.*?)\n\s*```",  # Markdown JSON block
            r"```\s*\n(.*?)\n\s*```",       # Generic code block
            r"(\{.*\})",                       # Any JSON-like object
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue
        # Try parsing the whole text as JSON
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            return None

    def minimal_fallback(self, context: Dict[str, Any]) -> TurnProposal:
        """Return a minimal valid TurnProposal when all repair fails."""
        user_input = context.get("user_input", "")
        return TurnProposal(
            narration=f"Time passes. The world around you remains still as you contemplate your next move.",
            npc_dialogue=[],
            state_delta=StateDelta(),
            next_options=[
                "Look around carefully.",
                "Wait and observe.",
                "Try a different approach."
            ]
        )
