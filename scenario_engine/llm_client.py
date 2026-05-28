"""LLM client adapter for PiperScenarioLab.

This lab stays standalone by default. The optional Piper seam is intentionally
lightweight: if a compatible Piper client cannot be imported, the adapter falls
back to mock behavior instead of crashing the app.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from scenario_engine.models import (
    DialogueLine,
    Scenario,
    StateDelta,
    TurnProposal,
)


class LLMMode(str, Enum):
    MOCK = "mock"
    PIPER = "piper"


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
            "and at the center you see fresh ash arranged in a deliberate pattern — the same symbol "
            "from the medallion. The truth is beginning to take shape."
        ),
        "npc_dialogue": [
            {
                "speaker_id": "mara_bellkeeper",
                "speaker_name": "Mara",
                "role": "Bellkeeper",
                "tone": "solemn",
                "text": "You see it now, don't you? The bell was never just a bell. It was a seal.",
            },
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

    async def generate_turn(
        self, prompt: str, scenario: Scenario, context: Dict[str, Any]
    ) -> TurnProposal:
        """Generate a TurnProposal. Mock mode returns canned responses."""
        if self.mode == LLMMode.MOCK:
            turn_number = context.get("turn_number", 1)
            mock_data = _MOCK_RESPONSES[(turn_number - 1) % len(_MOCK_RESPONSES)]
            return TurnProposal.model_validate(mock_data)

        # PIPER mode — would call external LLM
        return await self._generate_turn_piper(prompt, scenario, context)

    async def _generate_turn_piper(
        self, prompt: str, scenario: Scenario, context: Dict[str, Any]
    ) -> TurnProposal:
        """Placeholder for Piper LLM integration.

        The standalone lab does not depend on Piper at runtime. If callers want
        real Piper-backed generation they should use ``PiperLLMAdapter``.
        """
        # In a real implementation, this would call the Piper LLM client
        # and parse the response into a TurnProposal.
        turn_number = context.get("turn_number", 1)
        mock_data = _MOCK_RESPONSES[(turn_number - 1) % len(_MOCK_RESPONSES)]
        return TurnProposal.model_validate(mock_data)

    async def repair_json(self, broken_json: str, schema_hint: str = "") -> Optional[Dict[str, Any]]:
        """Attempt to repair invalid JSON. Mock mode returns minimal valid dict."""
        if self.mode == LLMMode.MOCK:
            return {
                "narration": "(Mock repair fallback — something happened, but details are unclear.)",
                "npc_dialogue": [],
                "state_delta": {},
                "next_options": ["Continue"],
            }

        # PIPER mode — would call external LLM for repair
        return None

    async def build_scenario(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Build a scenario from description. Mock returns None."""
        if self.mode == LLMMode.MOCK:
            return None

        # PIPER mode — would call external LLM
        return None


class PiperLLMAdapter(LLMClient):
    """Thin adapter around Piper's nearby llama-server client seam.

    The clearest current integration point in the sibling Piper repo is
    ``llm/llm_server_client.py`` and its ``LlamaServerClient.generate()``
    interface, which accepts OpenAI-style chat messages and returns text.

    This adapter does not force that dependency. If a compatible client or
    import path is unavailable, it records the reason and falls back to mock
    mode so ``SCENARIO_LLM_MODE=piper`` still starts cleanly.
    """

    def __init__(self, piper_client: Any = None, piper_repo_dir: str | None = None):
        mode = LLMMode.PIPER
        config: Dict[str, Any] = {}
        fallback_reason: Optional[str] = None

        if piper_client is not None:
            config["piper_client"] = piper_client
        else:
            resolved_client, fallback_reason = self._load_piper_client(piper_repo_dir)
            if resolved_client is not None:
                config["piper_client"] = resolved_client
            else:
                mode = LLMMode.MOCK

        super().__init__(mode=mode, config=config)
        self.piper_client = config.get("piper_client")
        self.fallback_reason = fallback_reason

    @staticmethod
    def _candidate_repo_dirs(explicit_repo_dir: str | None = None) -> List[Path]:
        candidates: List[Path] = []
        if explicit_repo_dir:
            candidates.append(Path(explicit_repo_dir))

        env_repo_dir = Path(__file__).resolve().parents[2]
        candidates.append(env_repo_dir / "Piper")
        candidates.append(Path("/mnt/c/Projects/Piper"))

        deduped: List[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    @classmethod
    def _load_piper_client(cls, explicit_repo_dir: str | None = None) -> tuple[Any | None, Optional[str]]:
        import importlib
        import sys

        errors: List[str] = []

        for repo_dir in cls._candidate_repo_dirs(explicit_repo_dir):
            client_path = repo_dir / "llm" / "llm_server_client.py"
            if not client_path.exists():
                errors.append(f"missing {client_path}")
                continue
            if str(repo_dir) not in sys.path:
                sys.path.insert(0, str(repo_dir))
            try:
                module = importlib.import_module("llm.llm_server_client")
            except Exception as exc:
                errors.append(f"{client_path}: {exc}")
                continue

            client_cls = getattr(module, "LlamaServerClient", None)
            cfg_cls = getattr(module, "LlamaServerConfig", None)
            if client_cls is None or cfg_cls is None:
                errors.append(f"{client_path}: missing LlamaServerClient/LlamaServerConfig")
                continue
            return {"client_cls": client_cls, "config_cls": cfg_cls, "repo_dir": str(repo_dir)}, None

        return None, "; ".join(errors) if errors else "Piper client not found"

    async def generate_turn(
        self, prompt: str, scenario: Scenario, context: Dict[str, Any]
    ) -> TurnProposal:
        # Real Piper transport is intentionally deferred. Until wired, we keep
        # the app stable by using the mock proposal path when the transport is
        # unavailable or not yet configured.
        return await super().generate_turn(prompt, scenario, context)
