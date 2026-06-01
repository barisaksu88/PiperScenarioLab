"""LLM client adapter for PiperScenarioLab."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from enum import Enum
from pathlib import Path
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
            "used_skills": [],
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
            "used_skills": [],
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
            "used_skills": [],
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
            "used_skills": [],
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
            "flags": {"discovered_truth": True},
            "inventory_add": [],
            "inventory_remove": [],
            "clues_add": ["ash_symbol"],
            "skills_add": [],
            "used_skills": [],
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

    async def generate_dialogue(self, prompt: str, scenario: Scenario, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate dialogue-only payloads for recovery when a turn omits spoken lines."""
        if self.mode == LLMMode.MOCK:
            return [
                {
                    "speaker_id": "mara_bellkeeper",
                    "speaker_name": "Mara",
                    "role": "Bellkeeper",
                    "tone": "cautious",
                    "text": "You're asking the right questions. The bell has not been silent by accident.",
                }
            ]
        return []


class PiperLLMAdapter(LLMClient):
    """HTTP adapter for a local llama.cpp-compatible server."""

    def __init__(self, piper_client: Any = None, piper_repo_dir: str | None = None, config: Optional[Dict[str, Any]] = None):
        del piper_client, piper_repo_dir
        cfg = config or {}
        base_url = str(
            cfg.get("base_url")
            or os.environ.get("SCENARIO_LLM_BASE_URL")
            or "http://127.0.0.1:8081"
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

    @property
    def _cache_dir(self) -> Path:
        return Path(os.environ.get("SCENARIO_LLM_CACHE_DIR", ".cache/llm_responses"))

    def _cache_key(self, payload: Dict[str, Any]) -> str:
        """Hash the payload to create a cache key."""
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _get_cached(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return cached response if available, else None."""
        if os.environ.get("SCENARIO_LLM_CACHE", "0") != "1":
            return None
        key = self._cache_key(payload)
        path = self._cache_dir / f"{key}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                LOG.debug("LLM cache hit: %s", key[:16])
                return data
            except Exception:
                pass
        return None

    def _save_cached(self, payload: Dict[str, Any], response: Dict[str, Any]) -> None:
        """Save response to disk cache."""
        if os.environ.get("SCENARIO_LLM_CACHE", "0") != "1":
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        key = self._cache_key(payload)
        path = self._cache_dir / f"{key}.json"
        try:
            path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
            LOG.debug("LLM cache saved: %s", key[:16])
        except Exception as exc:
            LOG.warning("Failed to save LLM cache: %s", exc)

    def build_messages(self, prompt: str) -> List[Dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are a narrator for an interactive story engine. "
                    "Your output must be valid JSON only. No markdown fences. No extra commentary before or after the JSON. "
                    "When NPCs are present in the scene, you MUST include at least one spoken dialogue line in npc_dialogue. "
                    "Never repeat the same narration from previous turns. Always advance the story."
                ),
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
            "max_tokens": 4000,
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
        """Ask the LLM to repair broken JSON, then extract and return it."""
        from scenario_engine.repair import Repair

        # First try a simple extraction in case it's just wrapped in text
        simple = Repair.extract_json(broken_json)
        if simple is not None:
            return simple

        # Otherwise ask the LLM to fix it
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a JSON repair tool. "
                    "The user will provide broken or malformed JSON. "
                    "Return ONLY valid JSON. No markdown fences. No extra commentary."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Fix this broken JSON so it is valid.\n"
                    f"Schema hint: {schema_hint or 'a single JSON object'}\n\n"
                    f"Broken input:\n{broken_json[:2000]}\n\n"
                    f"Return only the fixed JSON."
                ),
            },
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "stream": False,
            "max_tokens": 2000,
        }
        try:
            raw = await self._post_json(payload)
            content = self._extract_content(raw)
        except Exception as exc:
            LOG.warning("LLM repair call failed: %s", exc)
            return None
        return Repair.extract_json(content)

    async def generate_dialogue(self, prompt: str, scenario: Scenario, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        del scenario
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a dialogue writer for an interactive story. "
                    "Return ONLY valid JSON with a single key npc_dialogue containing an array of dialogue objects. "
                    "Each object must have: speaker_id, speaker_name, role, tone, text. "
                    "Do not narrate. Do not add commentary. Do not return empty npc_dialogue."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        if _debug_enabled():
            run_dir = get_current_debug_run_dir()
            if run_dir is not None:
                write_jsonl(run_dir / "llm_http_payload_debug.jsonl", {
                    "mode": "dialogue_repair",
                    "messages": messages,
                    "model": self.model,
                    "base_url": self.base_url,
                    "context": context,
                })
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.4,
            "stream": False,
            "max_tokens": 800,
        }
        raw = await self._post_json(payload)
        content = self._extract_content(raw)
        if _debug_enabled():
            run_dir = get_current_debug_run_dir()
            if run_dir is not None:
                write_text_artifact("raw_dialogue_response.txt", content)
        from scenario_engine.repair import Repair

        extracted = Repair.extract_json(content) or {}
        dialogue = extracted.get("npc_dialogue") or []
        return dialogue if isinstance(dialogue, list) else []

    async def _post_json(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cached = self._get_cached(payload)
        if cached is not None:
            return cached

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
            response = json.loads(data)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"Local LLM returned invalid JSON payload: {exc}") from exc
        self._save_cached(payload, response)
        return response

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
