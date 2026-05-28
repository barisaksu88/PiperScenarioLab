"""LLM client adapter for PiperScenarioLab."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from enum import Enum
from typing import Any, Dict, List, Optional

from scenario_engine.models import Scenario, TurnProposal
from scenario_engine.debug import get_current_debug_run_dir, write_jsonl, write_text_artifact

LOG = logging.getLogger(__name__)


class LLMMode(str, Enum):
    MOCK = "mock"
    PIPER = "piper"


class LLMClientError(RuntimeError):
    """Raised when the local LLM backend cannot be reached or returns unusable output."""


def _debug_enabled() -> bool:
    return os.environ.get("SCENARIO_DEBUG_LLM", "").strip() == "1"


def _shorten(text: str, limit: int = 4000) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "...[truncated]"


# Pre-built mock responses that exercise different delta types.
_MOCK_RESPONSES: List[Dict[str, Any]] = [
    {
        "narration": (
            "The village square is quiet except for the wind rustling through the old oak trees. "
            "Mara stands near the bell tower, her arms crossed as she watches you approach."
        ),
        "npc_dialogue": [
            {
                "speaker_id": "mara_bellkeeper",
                "speaker_name": "Mara",
                "role": "Bellkeeper",
                "tone": "guarded",
                "text": "You're new here. Not many strangers find their way to our village these days.",
            }
        ],
        "state_delta": {
            "flags": {"met_mara": True},
            "inventory_add": [],
            "inventory_remove": [],
            "clues_add": [],
            "skills_add": [],
            "relationship_changes": [{"npc_id": "mara_bellkeeper", "trust": 5}],
            "move_player_to_scene": None,
            "move_npc_to_scene": [],
            "complete_objectives": [],
            "fail_objectives": [],
            "npc_status_changes": {},
        },
        "next_options": [
            "Ask about the bell tower",
            "Introduce yourself warmly",
            "Look around the village square",
        ],
    },
    {
        "narration": (
            "Mara's expression softens slightly as you speak. She glances toward the bell tower, "
            "then back at you with a measured look. 'There's more to this place than meets the eye,' she says quietly."
        ),
        "npc_dialogue": [
            {
                "speaker_id": "mara_bellkeeper",
                "speaker_name": "Mara",
                "role": "Bellkeeper",
                "tone": "cautious",
                "text": "The bell... it didn't just break. Something was taken from beneath it. Old tracks lead toward the ruins.",
            }
        ],
        "state_delta": {
            "flags": {"mara_shared_clue": True},
            "inventory_add": [],
            "inventory_remove": [],
            "clues_add": ["old_tracks"],
            "skills_add": [],
            "relationship_changes": [{"npc_id": "mara_bellkeeper", "trust": 10, "respect": 5}],
            "move_player_to_scene": None,
            "move_npc_to_scene": [],
            "complete_objectives": ["question_mara"],
            "fail_objectives": [],
            "npc_status_changes": {},
        },
        "next_options": [
            "Ask about what was taken",
            "Go to the hilltop ruins",
            "Thank Mara and explore the square",
        ],
    },
    {
        "narration": (
            "You find a cracked silver medallion half-buried in the dirt near the old well. "
            "Its surface is warm to the touch, etched with symbols you don't recognize."
        ),
        "npc_dialogue": [],
        "state_delta": {
            "flags": {"found_medallion": True},
            "inventory_add": ["cracked_silver_medallion"],
            "inventory_remove": [],
            "clues_add": ["ash_symbol"],
            "skills_add": [],
            "relationship_changes": [],
            "move_player_to_scene": None,
            "move_npc_to_scene": [],
            "complete_objectives": ["inspect_village_square"],
            "fail_objectives": [],
            "npc_status_changes": {},
        },
        "next_options": [
            "Examine the medallion closely",
            "Show the medallion to Mara",
            "Head to the bell tower",
        ],
    },
    {
        "narration": (
            "The mayor's office is lavishly furnished, a stark contrast to the rest of the village. "
            "Eldric smiles smoothly from behind his desk, gesturing for you to sit."
        ),
        "npc_dialogue": [
            {
                "speaker_id": "eldric_mayor",
                "speaker_name": "Eldric",
                "role": "Mayor",
                "tone": "smooth",
                "text": "Welcome, welcome! I do hope Mara hasn't been troubling you with old wives' tales. Pay her no mind.",
            },
            {
                "speaker_id": "mara_bellkeeper",
                "speaker_name": "Mara",
                "role": "Bellkeeper",
                "tone": "sharp",
                "text": "Don't let him charm you. Ask about the cellar beneath his office.",
            },
        ],
        "state_delta": {
            "flags": {"met_eldric": True, "mayor_lied": True},
            "inventory_add": [],
            "inventory_remove": [],
            "clues_add": ["mayor_lied", "hidden_cellar"],
            "skills_add": [],
            "relationship_changes": [
                {"npc_id": "eldric_mayor", "trust": -10, "hostility": 5},
                {"npc_id": "mara_bellkeeper", "trust": 5, "respect": 5},
            ],
            "move_player_to_scene": "mayor_office",
            "move_npc_to_scene": [],
            "complete_objectives": [],
            "fail_objectives": [],
            "npc_status_changes": {},
        },
        "next_options": [
            "Confront Eldric about the cellar",
            "Play along and gather more information",
            "Return to the village square",
        ],
    },
    {
        "narration": (
            "The hilltop ruins loom against the darkening sky. Ancient stones form a circle, "
            "and at the center you see fresh ash arranged in a deliberate pattern -- the same symbol "
            "from the medallion. The truth is beginning to take shape."
        ),
        "npc_dialogue": [
            {
                "speaker_id": "mara_bellkeeper",
                "speaker_name": "Mara",
                "role": "Bellkeeper",
                "tone": "solemn",
                "text": "You see it now, don't you? The bell was never just a bell. It was a seal.",
            }
        ],
        "state_delta": {
            "flags": {"discovered_truth": True, "act_2_complete": True},
            "inventory_add": [],
            "inventory_remove": [],
            "clues_add": ["ash_symbol"],
            "skills_add": [],
            "relationship_changes": [{"npc_id": "mara_bellkeeper", "trust": 15, "respect": 10}],
            "move_player_to_scene": "hilltop_ruins",
            "move_npc_to_scene": [{"npc_id": "mara_bellkeeper", "scene_id": "hilltop_ruins"}],
            "complete_objectives": ["discover_truth"],
            "fail_objectives": [],
            "npc_status_changes": {},
        },
        "next_options": [
            "Ask Mara about the seal",
            "Investigate the ash symbol",
            "Return to confront Eldric",
        ],
    },
]


class LLMClient:
    """Adapter interface for LLM backends."""

    def __init__(self, mode: LLMMode = LLMMode.MOCK, config: Optional[Dict[str, Any]] = None):
        self.mode = mode
        self.config = config or {}

    async def generate_turn(self, prompt: str, scenario: Scenario, context: Dict[str, Any]) -> TurnProposal:
        """Generate a TurnProposal."""
        if self.mode == LLMMode.MOCK:
            turn_number = context.get("turn_number", 1)
            mock_data = _MOCK_RESPONSES[(turn_number - 1) % len(_MOCK_RESPONSES)]
            return TurnProposal.model_validate(mock_data)
        return await self._generate_turn_piper(prompt, scenario, context)

    async def _generate_turn_piper(self, prompt: str, scenario: Scenario, context: Dict[str, Any]) -> TurnProposal:
        return await PiperLLMAdapter(config=self.config).generate_turn(prompt, scenario, context)

    async def repair_json(self, broken_json: str, schema_hint: str = "") -> Optional[Dict[str, Any]]:
        if self.mode == LLMMode.MOCK:
            return {
                "narration": "(Mock repair fallback - something happened, but details are unclear.)",
                "npc_dialogue": [],
                "state_delta": {},
                "next_options": ["Continue"],
            }
        return None

    async def build_scenario(self, prompt: str) -> Optional[Dict[str, Any]]:
        if self.mode == LLMMode.MOCK:
            return None
        return None


class PiperLLMAdapter(LLMClient):
    """HTTP adapter for a local llama.cpp-compatible server."""

    def __init__(self, piper_client: Any = None, piper_repo_dir: str | None = None, config: Optional[Dict[str, Any]] = None):
        del piper_client, piper_repo_dir
        cfg = config or {}
        base_url = str(
            cfg.get("base_url")
            or os.environ.get("SCENARIO_LLM_BASE_URL")
            or "http://127.0.0.1:8080"
        )
        model = str(cfg.get("model") or os.environ.get("SCENARIO_LLM_MODEL") or "qwen")
        timeout_seconds = float(
            cfg.get("timeout_seconds")
            or os.environ.get("SCENARIO_LLM_TIMEOUT_SECONDS")
            or 30.0
        )
        super().__init__(
            mode=LLMMode.PIPER,
            config={
                "base_url": base_url,
                "model": model,
                "timeout_seconds": timeout_seconds,
            },
        )

    @property
    def base_url(self) -> str:
        return str(self.config["base_url"])

    @property
    def model(self) -> str:
        return str(self.config["model"])

    @property
    def timeout_seconds(self) -> float:
        return float(self.config["timeout_seconds"])

    def build_messages(self, prompt: str) -> List[Dict[str, str]]:
        return [
            {
                "role": "system",
                "content": "You are a strict JSON-only narrator for PiperScenarioLab. Return only valid JSON matching the TurnProposal schema.",
            },
            {"role": "user", "content": prompt},
        ]

    async def generate_turn(self, prompt: str, scenario: Scenario, context: Dict[str, Any]) -> TurnProposal:
        del scenario, context
        messages = self.build_messages(prompt)
        if _debug_enabled():
            LOG.debug("piper mode prompt length=%s messages=%s", len(prompt), len(messages))
            run_dir = get_current_debug_run_dir()
            if run_dir is not None:
                write_jsonl(run_dir / "llm_http_payload_debug.jsonl", {"messages": messages, "model": self.model, "base_url": self.base_url})
                write_text_artifact("rendered_prompt.txt", prompt)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "stream": False,
            "max_tokens": 1200,
        }
        raw = await self._post_json(payload)
        content = self._extract_content(raw)
        if _debug_enabled():
            LOG.debug("raw llm response: %s", _shorten(content))
            run_dir = get_current_debug_run_dir()
            if run_dir is not None:
                write_text_artifact("raw_llm_response.txt", content)
        from scenario_engine.repair import Repair

        proposal = await Repair(self).parse_turn_output(content, context={})
        if _debug_enabled():
            LOG.debug("parsed proposal: %s", proposal.model_dump(mode="json"))
            run_dir = get_current_debug_run_dir()
            if run_dir is not None:
                write_jsonl(run_dir / "turn_debug.jsonl", {"parsed_turn_proposal": proposal.model_dump(mode="json")})
        return proposal

    async def repair_json(self, broken_json: str, schema_hint: str = "") -> Optional[Dict[str, Any]]:
        del schema_hint
        from scenario_engine.repair import Repair

        repaired = Repair.extract_json(broken_json)
        return repaired

    async def _post_json(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url.rstrip("/") + "/v1/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise LLMClientError(f"Unable to reach local LLM at {self.base_url}: {exc}") from exc
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"Local LLM returned invalid JSON payload: {exc}") from exc

    @staticmethod
    def _extract_content(response: Dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            raise LLMClientError("Local LLM response was missing choices")
        first = choices[0] or {}
        if isinstance(first.get("message"), dict):
            return str(first["message"].get("content") or "")
        if isinstance(first.get("text"), str):
            return first["text"]
        delta = first.get("delta") or {}
        return str(delta.get("content") or "")
