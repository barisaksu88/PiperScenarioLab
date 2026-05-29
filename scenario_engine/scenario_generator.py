"""Scenario generator using multi-stage LLM prompting (pyramid style)."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from scenario_engine.models import (
    Act,
    Item,
    NPC,
    NPCPersona,
    NPCRelationship,
    Objective,
    Scene,
    Scenario,
    ScenarioMetadata,
    ScenarioProfile,
    Skill,
)
from scenario_engine.repair import Repair

LOG = logging.getLogger(__name__)


class ScenarioGeneratorError(RuntimeError):
    """Raised when scenario generation fails."""


class ScenarioGenerator:
    """Generate playable scenarios via structured multi-stage LLM calls."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "qwen",
        timeout_seconds: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.repair = Repair(llm_client=None)  # type: ignore[arg-type]

    def _post_json(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url + "/v1/chat/completions"
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
            raise ScenarioGeneratorError(f"LLM unreachable at {self.base_url}: {exc}") from exc
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise ScenarioGeneratorError(f"LLM returned invalid JSON: {exc}") from exc

    def _extract_content(self, response: Dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            raise ScenarioGeneratorError("LLM response missing choices")
        first = choices[0] or {}
        if isinstance(first.get("message"), dict):
            return str(first["message"].get("content") or "")
        if isinstance(first.get("text"), str):
            return first["text"]
        delta = first.get("delta") or {}
        return str(delta.get("content") or "")

    def _generate_json(self, messages: List[Dict[str, str]], max_tokens: int = 2000) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.75,
            "stream": False,
            "max_tokens": max_tokens,
        }
        raw = self._post_json(payload)
        content = self._extract_content(raw)
        extracted = Repair.extract_json(content)
        if extracted is None:
            # Try to repair truncated JSON (common when max_tokens is hit)
            completed = self._complete_truncated_json(content)
            if completed is not None:
                extracted = Repair.extract_json(completed)
            if extracted is None:
                raise ScenarioGeneratorError(
                    f"Could not extract JSON from LLM output. "
                    f"The response may have been truncated. Try a shorter scenario length.\n"
                    f"Preview: {content[:400]}"
                )
        return extracted

    @staticmethod
    def _complete_truncated_json(text: str) -> Optional[str]:
        """Best-effort repair of JSON truncated by max_tokens limit.

        Adds missing closing quotes, braces, and brackets to balance the structure.
        Returns the repaired text, or None if no opening brace was found.
        """
        text = text.strip()
        if not text:
            return None

        # Find the start of the JSON object
        start = text.find("{")
        if start == -1:
            return None
        text = text[start:]

        # Check if we end inside a string
        in_string = False
        escape = False
        for ch in text:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string

        # If inside a string, close it
        if in_string:
            text = text + '"'

        # Track open braces/brackets with a stack so closers are added
        # in the correct nested order.
        stack: list[str] = []
        in_string = False
        escape = False
        for ch in text:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue

            if ch == "{" or ch == "[":
                stack.append(ch)
            elif ch == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
            elif ch == "]":
                if stack and stack[-1] == "[":
                    stack.pop()

        closers = {"{": "}", "[": "]"}
        text = text + "".join(closers[c] for c in reversed(stack))

        return text

    # ------------------------------------------------------------------
    # Stage 1: Premise
    # ------------------------------------------------------------------
    def _stage1_premise(
        self,
        title_hint: str,
        genre: str,
        length: str,
        difficulty: str,
        tone: str,
        theme: str,
    ) -> Dict[str, Any]:
        length_map = {"short": (2, 15), "medium": (3, 30), "long": (4, 60)}
        num_acts, duration = length_map.get(length.lower(), (3, 30))

        prompt = (
            f"Create a concise scenario premise for a {length} {genre} story.\n"
            f"Theme: {theme}\n"
            f"Tone: {tone}\n"
            f"Difficulty: {difficulty}\n"
            f"Title hint: {title_hint or 'surprise me'}\n\n"
            "Respond with ONLY valid JSON matching this schema:\n"
            "{\n"
            '  "title": string,\n'
            '  "description": string (2-3 sentences hook),\n'
            '  "genre": string,\n'
            '  "estimated_duration_minutes": integer,\n'
            '  "num_acts": integer,\n'
            '  "overall_arc": string (1-2 sentences beginning-to-end),\n'
            '  "opening_scene_description": string (where the player starts),\n'
            '  "ending_scene_description": string (how it should conclude)\n'
            "}\n"
            "No extra commentary. No markdown fences."
        )
        messages = [
            {"role": "system", "content": "You are a concise scenario writer for an interactive story engine. Output strict JSON only."},
            {"role": "user", "content": prompt},
        ]
        data = self._generate_json(messages, max_tokens=2000)
        data["num_acts"] = data.get("num_acts", num_acts)
        data["estimated_duration_minutes"] = data.get("estimated_duration_minutes", duration)
        return data

    # ------------------------------------------------------------------
    # Stage 2: Entities (NPCs, Items, Skills)
    # ------------------------------------------------------------------
    def _stage2_entities(self, premise: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (
            f"Create NPCs, items, and skills for this scenario.\n\n"
            f"Title: {premise['title']}\n"
            f"Arc: {premise['overall_arc']}\n"
            f"Opening: {premise['opening_scene_description']}\n"
            f"Ending: {premise['ending_scene_description']}\n\n"
            "Rules:\n"
            "- Create 2-5 NPCs with distinct voices, motives, fears, temperament, and speech_style.\n"
            "- Each NPC has a relationship_to_player starting at 0 trust/fear/hostility/respect.\n"
            "- NPCs know things and can_reveal clues.\n"
            "- Create 0-4 items with descriptions and categories (artifact, tool, consumable, general).\n"
            "- Create 1-3 skills with descriptions and categories (general).\n"
            "- Use snake_case IDs prefixed with npc_, item_, skill_.\n\n"
            "Respond with ONLY valid JSON:\n"
            "{\n"
            '  "npcs": [\n'
            '    {\n'
            '      "id": "npc_...",\n'
            '      "name": string,\n'
            '      "role": string,\n'
            '      "current_scene": "",\n'
            '      "persona": {\n'
            '        "voice": string,\n'
            '        "motives": [string],\n'
            '        "fears": [string],\n'
            '        "temperament": string,\n'
            '        "speech_style": string\n'
            '      },\n'
            '      "relationship_to_player": {"trust": 0, "fear": 0, "hostility": 0, "respect": 0},\n'
            '      "knows": [string],\n'
            '      "can_reveal": [string],\n'
            '      "triggers": [],\n'
            '      "status": "available"\n'
            '    }\n'
            '  ],\n'
            '  "items": [\n'
            '    {\n'
            '      "id": "item_...",\n'
            '      "name": string,\n'
            '      "description": string,\n'
            '      "category": string\n'
            '    }\n'
            '  ],\n'
            '  "skills": [\n'
            '    {\n'
            '      "id": "skill_...",\n'
            '      "name": string,\n'
            '      "description": string,\n'
            '      "category": "general"\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "No extra commentary. No markdown fences."
        )
        messages = [
            {"role": "system", "content": "You are a character and item designer for an interactive story engine. Output strict JSON only."},
            {"role": "user", "content": prompt},
        ]
        return self._generate_json(messages, max_tokens=8000)

    # ------------------------------------------------------------------
    # Stage 3: Structure (Acts & Scenes)
    # ------------------------------------------------------------------
    def _stage3_structure(self, premise: Dict[str, Any], entities: Dict[str, Any]) -> Dict[str, Any]:
        num_acts = premise.get("num_acts", 3)
        npc_ids = [n["id"] for n in entities.get("npcs", [])]
        item_ids = [i["id"] for i in entities.get("items", [])]
        prompt = (
            f"Based on this premise and entities, design the act/scene structure for a {num_acts}-act interactive scenario.\n\n"
            f"Title: {premise['title']}\n"
            f"Arc: {premise['overall_arc']}\n"
            f"Opening: {premise['opening_scene_description']}\n"
            f"Ending: {premise['ending_scene_description']}\n\n"
            f"Available NPCs: {npc_ids}\n"
            f"Available Items: {item_ids}\n\n"
            "Rules:\n"
            "- Each act has 1-3 connected scenes.\n"
            "- Every scene (except the first) must be connected from at least one other scene in the SAME act or the previous act.\n"
            "- Each act has 1-2 objectives.\n"
            "- The FINAL act must include an 'ending_narration' field (2-3 sentences wrapping the conclusion).\n"
            "- ONLY use NPC and item IDs from the lists above. Do not invent new ones.\n"
            "- Use snake_case IDs for scenes and acts.\n"
            "- Keep descriptions concise (1-2 sentences) to stay within token limits.\n\n"
            "Respond with ONLY valid JSON:\n"
            "{\n"
            '  "acts": [\n'
            '    {\n'
            '      "id": "act_1_...",\n'
            '      "name": string,\n'
            '      "description": string,\n'
            '      "scenes": [\n'
            '        {\n'
            '          "id": "scene_...",\n'
            '          "name": string,\n'
            '          "description": string,\n'
            '          "connected_scenes": ["other_scene_id"],\n'
            '          "npcs_present": ["npc_id_or_empty"],\n'
            '          "items_present": ["item_id_or_empty"],\n'
            '          "clues_present": ["clue_id_or_empty"]\n'
            '        }\n'
            '      ],\n'
            '      "objectives": [\n'
            '        {\n'
            '          "id": "obj_...",\n'
            '          "description": string,\n'
            '          "required_flags": ["flag_name_or_empty"],\n'
            '          "required_clues": ["clue_name_or_empty"]\n'
            '        }\n'
            '      ],\n'
            '      "completion_flags": ["flag_name"],\n'
            '      "ending_narration": string (only for final act)\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "No extra commentary. No markdown fences."
        )
        messages = [
            {"role": "system", "content": "You are a structured game designer. Output strict JSON only."},
            {"role": "user", "content": prompt},
        ]
        return self._generate_json(messages, max_tokens=4000)

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------
    def _build_scenario(
        self,
        premise: Dict[str, Any],
        entities: Dict[str, Any],
        structure: Dict[str, Any],
        difficulty: str,
    ) -> Scenario:
        # Profile
        profile = ScenarioProfile(
            profile_id="generated",
            display_name="Generated",
            allowed_dynamic_creation=["flags"],
            validation_rules={"allow_dynamic_flags": True, "max_inventory": 20},
            prompt_template_dir="",
            ui_labels={
                "acts_label": "Acts",
                "scenes_label": "Locations",
                "npcs_label": "Characters",
                "items_label": "Inventory",
                "skills_label": "Abilities",
                "clues_label": "Clues",
            },
        )

        # Metadata
        metadata = ScenarioMetadata(
            title=premise.get("title", "Untitled Scenario"),
            description=premise.get("description", ""),
            author="PiperScenarioLab",
            version="1.0",
            profile_id="generated",
            difficulty=difficulty,
            estimated_duration_minutes=premise.get("estimated_duration_minutes", 30),
        )

        # Acts
        acts: Dict[str, Act] = {}
        first_scene_id = ""
        valid_npc_ids = {n["id"] for n in entities.get("npcs", [])}
        valid_item_ids = {i["id"] for i in entities.get("items", [])}
        for act_data in structure.get("acts", []):
            scenes: Dict[str, Scene] = {}
            for sc in act_data.get("scenes", []):
                scene = Scene(
                    id=sc.get("id", "scene_1"),
                    name=sc.get("name", "Unknown"),
                    description=sc.get("description", ""),
                    connected_scenes=sc.get("connected_scenes", []),
                    npcs_present=[nid for nid in sc.get("npcs_present", []) if nid in valid_npc_ids],
                    items_present=[iid for iid in sc.get("items_present", []) if iid in valid_item_ids],
                    clues_present=sc.get("clues_present", []),
                )
                scenes[scene.id] = scene
                if not first_scene_id:
                    first_scene_id = scene.id

            objectives: Dict[str, Objective] = {}
            for obj in act_data.get("objectives", []):
                objective = Objective(
                    id=obj.get("id", "obj_1"),
                    description=obj.get("description", ""),
                    required_flags=obj.get("required_flags", []),
                    required_clues=obj.get("required_clues", []),
                )
                objectives[objective.id] = objective

            act = Act(
                id=act_data.get("id", "act_1"),
                name=act_data.get("name", "Act 1"),
                description=act_data.get("description", ""),
                scenes=scenes,
                objectives=objectives,
                completion_flags=act_data.get("completion_flags", []),
                ending_narration=act_data.get("ending_narration") or "",
            )
            acts[act.id] = act

        # NPCs
        npcs: Dict[str, NPC] = {}
        for npc_data in entities.get("npcs", []):
            persona = NPCPersona(
                voice=npc_data.get("persona", {}).get("voice", ""),
                motives=npc_data.get("persona", {}).get("motives", []),
                fears=npc_data.get("persona", {}).get("fears", []),
                temperament=npc_data.get("persona", {}).get("temperament", ""),
                speech_style=npc_data.get("persona", {}).get("speech_style", ""),
            )
            rel = npc_data.get("relationship_to_player", {})
            raw_triggers = npc_data.get("triggers", [])
            triggers = []
            for t in raw_triggers:
                if isinstance(t, dict) and "condition" in t and "effect" in t:
                    triggers.append(t)
            npc = NPC(
                id=npc_data.get("id", "npc_1"),
                name=npc_data.get("name", "Unknown"),
                role=npc_data.get("role", ""),
                current_scene=npc_data.get("current_scene", first_scene_id),
                persona=persona,
                relationship_to_player=NPCRelationship(
                    trust=rel.get("trust", 0),
                    fear=rel.get("fear", 0),
                    hostility=rel.get("hostility", 0),
                    respect=rel.get("respect", 0),
                ),
                knows=npc_data.get("knows", []),
                can_reveal=npc_data.get("can_reveal", []),
                triggers=triggers,
                status=npc_data.get("status", "available"),
            )
            npcs[npc.id] = npc

        # Items
        items: Dict[str, Item] = {}
        for item_data in entities.get("items", []):
            item = Item(
                id=item_data.get("id", "item_1"),
                name=item_data.get("name", "Unknown"),
                description=item_data.get("description", ""),
                category=item_data.get("category", "general"),
            )
            items[item.id] = item

        # Skills
        skills: Dict[str, Skill] = {}
        for skill_data in entities.get("skills", []):
            skill = Skill(
                id=skill_data.get("id", "skill_1"),
                name=skill_data.get("name", "Unknown"),
                description=skill_data.get("description", ""),
                category=skill_data.get("category", "general"),
            )
            skills[skill.id] = skill

        # Validate and fix scene graph connectivity
        self._validate_and_fix_scene_graph(acts)

        # Player
        first_act_id = sorted(acts.keys())[0] if acts else ""
        from scenario_engine.models import PlayerState

        player = PlayerState(
            current_act=first_act_id,
            current_scene=first_scene_id,
            inventory=[],
            skills=list(skills.keys()),
            clues=[],
            flags={},
        )

        return Scenario(
            metadata=metadata,
            profile=profile,
            acts=acts,
            npcs=npcs,
            items=items,
            skills=skills,
            player=player,
        )

    @staticmethod
    def _validate_and_fix_scene_graph(acts: Dict[str, Act]) -> None:
        """Ensure every scene is reachable and the graph is playable.

        Rules enforced:
        - All connected_scenes entries must point to valid scene IDs.
        - Every scene (except the very first of the whole scenario) must have
          at least one incoming connection.
        - Connections are made bidirectional.
        - The first scene of each act (except the first act) is connected back
          to at least one scene in the previous act so act progression works.
        """
        if not acts:
            return

        # Build global scene registry
        all_scenes: Dict[str, Scene] = {}
        act_order = sorted(acts.keys())
        for act_id in act_order:
            all_scenes.update(acts[act_id].scenes)

        if not all_scenes:
            return

        # 1. Filter invalid connections and self-connections
        for scene in all_scenes.values():
            scene.connected_scenes = [
                sid for sid in scene.connected_scenes
                if sid in all_scenes and sid != scene.id
            ]

        # 2. Ensure bidirectional connections
        for scene in all_scenes.values():
            for sid in list(scene.connected_scenes):
                target = all_scenes[sid]
                if scene.id not in target.connected_scenes:
                    target.connected_scenes.append(scene.id)

        # 3. Ensure every scene (except the global first) has at least one connection
        first_scene_id = None
        for act_id in act_order:
            act = acts[act_id]
            if act.scenes:
                first_scene_id = sorted(act.scenes.keys())[0]
                break

        for scene in all_scenes.values():
            if scene.id == first_scene_id:
                continue
            if not scene.connected_scenes:
                # Connect to the first scene of the same act if possible,
                # otherwise to the global first scene
                act_id_for_scene = None
                for aid, act in acts.items():
                    if scene.id in act.scenes:
                        act_id_for_scene = aid
                        break
                same_act_first = None
                if act_id_for_scene:
                    same_act_first = sorted(acts[act_id_for_scene].scenes.keys())[0]
                fallback = same_act_first or first_scene_id
                if fallback and fallback != scene.id:
                    scene.connected_scenes.append(fallback)
                    # Make bidirectional
                    if scene.id not in all_scenes[fallback].connected_scenes:
                        all_scenes[fallback].connected_scenes.append(scene.id)

        # 4. Cross-act connectivity: first scene of act N+1 should connect back
        #    to at least one scene in act N
        for i in range(1, len(act_order)):
            prev_act = acts[act_order[i - 1]]
            curr_act = acts[act_order[i]]
            if not curr_act.scenes or not prev_act.scenes:
                continue
            curr_first_id = sorted(curr_act.scenes.keys())[0]
            curr_first = curr_act.scenes[curr_first_id]
            # Check if curr_first already connects to any scene in prev_act
            already_connected = any(
                sid in prev_act.scenes for sid in curr_first.connected_scenes
            )
            if not already_connected:
                # Connect to the last scene of the previous act
                prev_last_id = sorted(prev_act.scenes.keys())[-1]
                if prev_last_id != curr_first_id:
                    curr_first.connected_scenes.append(prev_last_id)
                    if curr_first_id not in prev_act.scenes[prev_last_id].connected_scenes:
                        prev_act.scenes[prev_last_id].connected_scenes.append(curr_first_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def generate(
        self,
        title_hint: str = "",
        genre: str = "fantasy",
        length: str = "short",
        difficulty: str = "medium",
        tone: str = "mysterious",
        theme: str = "",
    ) -> Scenario:
        """Generate a complete scenario from user preferences."""
        LOG.info("Stage 1: generating premise...")
        premise = self._stage1_premise(title_hint, genre, length, difficulty, tone, theme)
        LOG.info("Premise: %s", premise.get("title"))

        LOG.info("Stage 2: generating entities...")
        entities = self._stage2_entities(premise)

        LOG.info("Stage 3: generating structure...")
        structure = self._stage3_structure(premise, entities)

        LOG.info("Assembling scenario...")
        scenario = self._build_scenario(premise, entities, structure, difficulty)
        return scenario
