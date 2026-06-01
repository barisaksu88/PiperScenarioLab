"""Main scenario engine for PiperScenarioLab."""

from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scenario_engine.actor_selector import ActorSelector
from scenario_engine.dialogue import DialogueManager
from scenario_engine.debug import get_current_debug_run_dir, snapshot_state, write_jsonl
from scenario_engine.llm_client import LLMClient
from scenario_engine.models import (
    Act,
    CharacterStats,
    DialogueLine,
    NPC,
    PlayerState,
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
        self.scenario_id: Optional[str] = None
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
        self.scenario_id = scenario_id
        self.scenario = self.storage.load_scenario(scenario_id)
        self.validator = Validator(self.scenario, profile=None)
        self.actor_selector = ActorSelector(self.scenario)
        self.turn_number = 0

        # Initialize player stats (always generate fresh on load)
        if self.scenario is not None:
            self.scenario.player.stats = self._generate_character_stats()
            # Auto-pickup items in starting scene
            self._auto_pickup_items_in_current_scene()
            # Set NPCs to their initial scene positions
            self._update_npc_positions_by_schedule()

        initial_state = self._build_session_state_dict()
        self.storage.save_session(self.session_id, initial_state)

    def _generate_character_stats(self) -> CharacterStats:
        """Generate D&D-style character stats using 3d6 drop lowest (total 9-18 per stat)."""
        import random
        def roll_stat() -> int:
            rolls = sorted([random.randint(1, 6) for _ in range(4)])
            return sum(rolls[1:])  # drop lowest
        con = roll_stat()
        max_hp = 10 + (con - 10) // 2  # D&D 5e style: 10 + CON modifier
        return CharacterStats(
            strength=roll_stat(),
            dexterity=roll_stat(),
            constitution=con,
            intelligence=roll_stat(),
            wisdom=roll_stat(),
            charisma=roll_stat(),
            hp=max_hp,
            max_hp=max_hp,
            xp=0,
            level=1,
        )

    def _auto_pickup_items_in_current_scene(self) -> None:
        """Automatically add items_present in current scene to player inventory if not yet picked up."""
        if self.scenario is None:
            return
        current_scene = self._get_current_scene()
        if current_scene is None:
            return
        for item_id in current_scene.items_present:
            if item_id not in self.scenario.player.picked_up_items:
                if item_id not in self.scenario.player.inventory:
                    self.scenario.player.inventory.append(item_id)
                self.scenario.player.picked_up_items.append(item_id)

    def _advance_time_of_day(self) -> None:
        """Advance time of day after each turn."""
        cycle = ["morning", "afternoon", "evening", "night"]
        if self.scenario is None:
            return
        current = self.scenario.player.time_of_day or "morning"
        idx = cycle.index(current) if current in cycle else 0
        self.scenario.player.time_of_day = cycle[(idx + 1) % len(cycle)]

    def _update_npc_positions_by_schedule(self) -> None:
        """Move NPCs to their scheduled scene based on current time of day."""
        if self.scenario is None:
            return
        current_time = self.scenario.player.time_of_day or "morning"
        for npc in self.scenario.npcs.values():
            if npc.schedule and current_time in npc.schedule:
                npc.current_scene = npc.schedule[current_time]

    async def load_session(self, session_id: str) -> None:
        """Restore a previously saved session.

        Loads the full scenario state (objectives, NPCs, player, flags, etc.)
        from the saved session file so the game continues exactly where it left off.
        """
        saved = self.storage.load_session(session_id)
        if saved is None:
            raise FileNotFoundError(f"Session not found: {session_id}")

        # Prefer the embedded full scenario state if available.
        scenario_data = saved.get("scenario")
        if scenario_data:
            self.scenario = Scenario.model_validate(scenario_data)
        else:
            scenario_id = saved.get("scenario_id")
            if not scenario_id:
                raise RuntimeError("Saved session has no scenario_id and no embedded scenario data.")
            self.scenario_id = scenario_id
            self.scenario = self.storage.load_scenario(scenario_id)

        self.validator = Validator(self.scenario, profile=None)
        self.actor_selector = ActorSelector(self.scenario)
        self.session_id = session_id
        self.turn_number = saved.get("turn_number", 0)

    async def delete_session(self, session_id: str) -> None:
        """Delete a saved session and its log."""
        self.storage.delete_session(session_id)

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
        11. Check act progression / ending.
        12. Save session state.
        13. Return TurnResult.
        """
        if self.scenario is None:
            raise RuntimeError("No scenario loaded. Call load_scenario() first.")

        self.turn_number += 1

        # Step 2a: Validate player input for impossible actions
        rejection = self.validator.validate_player_input(turn_input.user_input)
        if rejection is not None:
            now = datetime.now(timezone.utc).isoformat()
            stats = self._calculate_score_stats()
            return TurnResult(
                turn_number=self.turn_number,
                narration=rejection,
                npc_dialogue=[],
                state_delta=StateDelta(),
                validation=ValidationResult(is_valid=False, warnings=["Player input rejected: impossible action"]),
                next_options=['Try a different approach.', 'Look around.', 'Wait and observe.'],
                used_skills=[],
                player_state=self.scenario.player.model_copy(deep=True),
                active_npcs=self._get_active_npcs(),
                current_act=self.scenario.player.current_act,
                current_scene=self._get_current_scene(),
                timestamp=now,
                **stats,
            )

        # Step 2b: Get current state
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
            run_dir = get_current_debug_run_dir()
            if run_dir is not None:
                write_jsonl(run_dir / "turn_debug.jsonl", {
                    "turn_number": self.turn_number,
                    "selected_actors": [npc.id for npc in selected_npcs],
                })

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
            run_dir = get_current_debug_run_dir()
            if run_dir is not None:
                write_jsonl(run_dir / "turn_debug.jsonl", {
                    "turn_number": self.turn_number,
                    "parsed_turn_proposal": raw_proposal.model_dump(mode="json"),
                })

        # Step 6: Validate the proposal
        validation = self.validator.validate_turn(raw_proposal)
        if _debug_enabled() and validation.rejected_changes:
            LOG.debug("validator rejected changes turn=%s changes=%s", self.turn_number, validation.rejected_changes)
            run_dir = get_current_debug_run_dir()
            if run_dir is not None:
                write_jsonl(run_dir / "validator_debug.jsonl", {
                    "turn_number": self.turn_number,
                    "rejected_changes": validation.rejected_changes,
                    "warnings": validation.warnings,
                    "accepted_delta": validation.accepted_delta.model_dump(mode="json"),
                })

        # Step 7: Apply accepted state delta
        self._apply_state_delta(validation.accepted_delta)

        # Step 7b: Advance time of day and update NPC positions
        self._advance_time_of_day()
        self._update_npc_positions_by_schedule()

        # Step 8: Process dialogue
        current_scene_id = self.scenario.player.current_scene
        dialogue = self.dialogue_manager.process_dialogue(
            raw_proposal.npc_dialogue, self.scenario, current_scene_id
        )
        if not dialogue and selected_npcs:
            dialogue = await self._recover_missing_dialogue(
                turn_input,
                selected_npcs,
                raw_proposal.narration,
                context,
            )
        if not dialogue and self._should_force_spoken_response(turn_input, selected_npcs):
            dialogue = self._fallback_spoken_response(turn_input, selected_npcs)

        # Step 8b: Detect used skills (fallback if LLM didn't report them)
        detected_skills = self._detect_used_skills(turn_input.user_input, raw_proposal.narration)
        used_skills = list(dict.fromkeys(validation.accepted_delta.used_skills + detected_skills))

        # Step 9: Build TurnResult
        now = datetime.now(timezone.utc).isoformat()
        stats = self._calculate_score_stats()
        turn_result = TurnResult(
            turn_number=self.turn_number,
            narration=raw_proposal.narration,
            npc_dialogue=dialogue,
            state_delta=validation.accepted_delta,
            validation=validation,
            next_options=raw_proposal.next_options,
            used_skills=used_skills,
            player_state=self.scenario.player.model_copy(deep=True),
            active_npcs=self._get_active_npcs(),
            current_act=self.scenario.player.current_act,
            current_scene=self._get_current_scene(),
            timestamp=now,
            **stats,
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

        # Step 11: Check act progression / ending
        progression = self._check_act_progression()
        if progression:
            if progression.get("ending"):
                turn_result.ending = progression["ending"]
                turn_result.narration = turn_result.narration + "\n\n" + progression["ending"]
            elif progression.get("transition"):
                turn_result.narration = turn_result.narration + "\n\n" + progression["transition"]

        # Step 12: Save session state
        session_state = self._build_session_state_dict()
        self.storage.save_session(self.session_id, session_state)
        if _debug_enabled():
            snapshot_state("session_snapshot_latest.json", self.get_state())

        return turn_result

    async def _recover_missing_dialogue(
        self,
        turn_input: TurnInput,
        selected_npcs: List[NPC],
        narration: str,
        context: Dict[str, Any],
    ) -> List[DialogueLine]:
        npc_block = []
        for npc in selected_npcs:
            npc_block.append(f"- {npc.name} ({npc.role}): {npc.persona.temperament}")
            if npc.persona.speech_style:
                npc_block.append(f"  speech_style: {npc.persona.speech_style}")
            if npc.persona.motives:
                npc_block.append(f"  motives: {', '.join(npc.persona.motives)}")
        prompt = (
            "Generate only NPC dialogue JSON for this turn.\n"
            "The previous turn omitted spoken lines even though NPCs are present. Recover the missing dialogue now.\n"
            f"Player input: {turn_input.user_input}\n"
            f"Narration so far: {narration}\n"
            f"NPCs present:\n{chr(10).join(npc_block) if npc_block else '(none)'}\n\n"
            "Return JSON exactly like:\n"
            '{"npc_dialogue":[{"speaker_id":"...","speaker_name":"...","role":"...","tone":"...","text":"..."}]}\n'
            "Use one or two lines max per NPC if the user is directly addressing the NPCs.\n"
            "Do not summarize speech in narration. Do not return empty dialogue when NPCs are present."
        )
        try:
            lines = await self.llm_client.generate_dialogue(prompt, self.scenario, context)
        except Exception as exc:
            LOG.warning("Dialogue recovery failed: %s", exc)
            return []
        if not lines:
            return []
        recovered: List[DialogueLine] = []
        for line in lines:
            try:
                recovered.append(DialogueLine.model_validate(line))
            except Exception:
                continue
        return self.dialogue_manager.process_dialogue(recovered, self.scenario, self.scenario.player.current_scene)

    def _should_force_spoken_response(self, turn_input: TurnInput, selected_npcs: List[NPC]) -> bool:
        if not selected_npcs:
            return False
        text = turn_input.user_input.lower()
        if any(
            token in text
            for token in (
                "ask",
                "tell",
                "say",
                "speak",
                "talk",
                "show",
                "mention",
                "point out",
                "bring up",
            )
        ):
            return True
        if "?" in text and any(token in text for token in ("mara", "you", "bell", "who", "what", "why", "how", "where")):
            return True
        return False

    def _fallback_spoken_response(self, turn_input: TurnInput, selected_npcs: List[NPC]) -> List[DialogueLine]:
        text = turn_input.user_input.lower()
        fallback_lines: List[DialogueLine] = []
        for npc in selected_npcs[:2]:
            fallback_text, tone = self._fallback_dialogue_text(text, npc)
            fallback_lines.append(
                DialogueLine(
                    speaker_id=npc.id,
                    speaker_name=npc.name,
                    role=npc.role,
                    tone=tone,
                    text=fallback_text,
                )
            )
        return self.dialogue_manager.process_dialogue(fallback_lines, self.scenario, self.scenario.player.current_scene)

    def _fallback_dialogue_text(self, text: str, npc: NPC) -> tuple[str, str]:
        text = text.lower()
        temperament = (npc.persona.temperament or "").lower()
        motives = [m.lower() for m in npc.persona.motives]
        fears = [f.lower() for f in npc.persona.fears]
        name = npc.name

        # Keyword-based overrides
        if "who are you" in text or "your name" in text or "introduce" in text:
            if "guard" in temperament or "cautious" in temperament:
                return f"I am {name}. You should tread carefully here.", "guarded"
            return f"I am {name}. I watch over this place.", "calm"

        if "?" in text or any(token in text for token in ("ask", "tell", "say", "speak", "talk", "show", "mention", "point out", "bring up")):
            if motives:
                return f"You ask much. {motives[0].capitalize()}—that is what drives me.", "cautious"
            if fears:
                return f"Be careful what you seek. {fears[0].capitalize()}... it is never far.", "guarded"
            if "smooth" in temperament or "charm" in temperament:
                return "An interesting question. Perhaps we can help each other.", "smooth"
            return "You're asking the right questions. Keep going and I may tell you more.", "cautious"

        if any(token in text for token in ("help", "aid", "assist")):
            if motives:
                return f"If you truly wish to help, remember this: {motives[0]}.", "earnest"
            return "Help is rare in these parts. Prove your intent.", "guarded"

        if any(token in text for token in ("attack", "fight", "kill", "threaten")):
            return f"{name} tenses, eyes narrowing. 'Violence will only deepen the shadow here.'", "cold"

        # Temperament-based defaults
        if "guard" in temperament or "suspicious" in temperament or "cautious" in temperament:
            return "I am watching. Speak your purpose.", "guarded"
        if "kind" in temperament or "warm" in temperament or "gentle" in temperament:
            return "You need not fear. I mean you no harm.", "warm"
        if "grim" in temperament or "solemn" in temperament or "dark" in temperament:
            return "The silence here holds many truths. Not all should be spoken.", "solemn"
        if "smooth" in temperament or "charm" in temperament:
            return "Ah, a newcomer. How delightful. What brings you to my corner of the world?", "charming"

        return "I'm listening. Go on.", "neutral"

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
            return SessionStateResponse(turn_number=self.turn_number, session_id=self.session_id)

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

        ending = None
        current_act = self._get_current_act()
        if current_act:
            flags_met = all(flag in self.scenario.player.flags for flag in current_act.completion_flags)
            if flags_met and current_act.ending_narration:
                ending = current_act.ending_narration

        stats = self._calculate_score_stats()

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
            ending=ending,
            session_id=self.session_id,
            stats=self.scenario.player.stats,
            time_of_day=self.scenario.player.time_of_day,
            **stats,
        )

    def get_session_log(self) -> List[SessionLogEntry]:
        """Return full session log."""
        return self.storage.load_session_log(self.session_id)

    def _detect_used_skills(self, user_input: str, narration: str) -> List[str]:
        """Heuristically detect skill usage from player input and narration."""
        if self.scenario is None:
            return []
        text = f"{user_input} {narration}".lower()
        found: List[str] = []
        for skill_id in self.scenario.player.skills:
            skill = self.scenario.skills.get(skill_id)
            if skill is None:
                continue
            names = {skill_id.lower(), skill.name.lower()}
            if any(name in text for name in names):
                found.append(skill_id)
        return found

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
        npc_names = []
        if selected_npcs:
            lines = []
            for npc in selected_npcs:
                npc_names.append(npc.name)
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

        # Build skills list with descriptions
        skills_list = ""
        if self.scenario.player.skills:
            skill_lines = []
            for skill_id in self.scenario.player.skills:
                skill = self.scenario.skills.get(skill_id)
                if skill:
                    skill_lines.append(f"- {skill.name}: {skill.description}")
                else:
                    skill_lines.append(f"- {skill_id}")
            skills_list = "\n".join(skill_lines)
        else:
            skills_list = "(none)"

        # Build flags string
        flags_str = json.dumps(self.scenario.player.flags, indent=2) if self.scenario.player.flags else "{}"

        # Build objectives string with prerequisites so the LLM knows when to complete them
        objectives_str = ""
        if current_act and current_act.objectives:
            lines = []
            for obj in current_act.objectives.values():
                status = obj.status
                req = []
                if obj.required_flags:
                    req.append(f"flags: {', '.join(obj.required_flags)}")
                if obj.required_clues:
                    req.append(f"clues: {', '.join(obj.required_clues)}")
                req_str = f" (requires {'; '.join(req)})" if req else ""
                lines.append(f"- {obj.description} [{status}]{req_str}")
            objectives_str = "\n".join(lines)
        else:
            objectives_str = "(none)"

        # Build completion flags string
        completion_flags_str = ""
        if current_act and current_act.completion_flags:
            completion_flags_str = ", ".join(current_act.completion_flags)
        else:
            completion_flags_str = "(none)"

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
        # Get player stats for prompt
        stats_str = "(none)"
        stats_hp_str = "0"
        stats_max_hp_str = "0"
        stats_level_str = "1"
        stats_xp_str = "0"
        if self.scenario.player.stats is not None:
            stats = self.scenario.player.stats
            stats_str = (
                f"STR {stats.strength}, DEX {stats.dexterity}, CON {stats.constitution}, "
                f"INT {stats.intelligence}, WIS {stats.wisdom}, CHA {stats.charisma}"
            )
            stats_hp_str = str(stats.hp)
            stats_max_hp_str = str(stats.max_hp)
            stats_level_str = str(stats.level)
            stats_xp_str = str(stats.xp)

        time_of_day = self.scenario.player.time_of_day or "morning"

        replacements = {
            "{scenario_title}": self.scenario.metadata.title,
            "{current_act}": act_name,
            "{current_scene}": scene_name,
            "{scene_description}": scene_description,
            "{npc_personas}": npc_personas,
            "{npc_names}": ", ".join(npc_names) or "(none)",
            "{inventory_list}": inventory_list,
            "{clues_list}": clues_list,
            "{skills_list}": skills_list,
            "{flags}": flags_str,
            "{objectives}": objectives_str,
            "{completion_flags}": completion_flags_str,
            "{recent_log}": recent_log,
            "{user_input}": turn_input.user_input,
            "{stats}": stats_str,
            "{stats_strength}": str(self.scenario.player.stats.strength) if self.scenario.player.stats else "10",
            "{stats_dexterity}": str(self.scenario.player.stats.dexterity) if self.scenario.player.stats else "10",
            "{stats_constitution}": str(self.scenario.player.stats.constitution) if self.scenario.player.stats else "10",
            "{stats_intelligence}": str(self.scenario.player.stats.intelligence) if self.scenario.player.stats else "10",
            "{stats_wisdom}": str(self.scenario.player.stats.wisdom) if self.scenario.player.stats else "10",
            "{stats_charisma}": str(self.scenario.player.stats.charisma) if self.scenario.player.stats else "10",
            "{stats_hp}": stats_hp_str,
            "{stats_max_hp}": stats_max_hp_str,
            "{stats_level}": stats_level_str,
            "{stats_xp}": stats_xp_str,
            "{time_of_day}": time_of_day,
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
            "Conversation candidates:\n{npc_names}\n\n"
            "Player inventory: {inventory_list}\n"
            "Player clues: {clues_list}\n"
            "Player skills:\n{skills_list}\n\n"
            "Player flags: {flags}\n\n"
            "Current act objectives:\n{objectives}\n\n"
            "Act completion flags needed: {completion_flags}\n\n"
            "Recent history:\n{recent_log}\n\n"
            "Player input: {user_input}\n\n"
            "Respond with ONLY valid JSON. Do not wrap in markdown fences. No extra text.\n\n"
            "Example format:\n"
            '{\n'
            '  "narration": "You step forward...",\n'
            '  "npc_dialogue": [{"speaker_id":"npc_guide","speaker_name":"Guide","role":"Mentor","tone":"cautious","text":"Watch your step."}],\n'
            '  "state_delta": {"flags":{"examined_door":true},"inventory_add":[],"inventory_remove":[],"clues_add":["hidden_latch"],"skills_add":[],"used_skills":[],"relationship_changes":[],"move_player_to_scene":null,"move_npc_to_scene":[],"complete_objectives":[],"fail_objectives":[],"npc_status_changes":{}},\n'
            '  "next_options": ["Push the door open","Knock and wait","Search for another way in"]\n'
            '}\n\n'
            "Rules:\n"
            "- narration must advance the story based on the player's input. Never repeat the same description.\n"
            "- If NPCs are present and the player addresses them, at least one NPC must speak with actual dialogue text.\n"
            "- state_delta.flags should include progress toward the act completion flags when appropriate.\n"
            "- When a player fulfills an objective's required flags/clues, include its id in state_delta.complete_objectives immediately.\n"
            "- If the player uses a skill they possess, include its id in state_delta.used_skills.\n"
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
            # Auto-pickup items in new scene
            self._auto_pickup_items_in_current_scene()

        # Apply stat changes
        if delta.stats_changes:
            stats = self.scenario.player.stats
            if stats is not None:
                for key, value in delta.stats_changes.items():
                    if hasattr(stats, key) and isinstance(value, (int, float)):
                        current = getattr(stats, key, 0)
                        setattr(stats, key, max(1, min(20, current + value)))

        # Apply HP changes
        if delta.hp_change != 0 and self.scenario.player.stats is not None:
            stats = self.scenario.player.stats
            stats.hp = max(0, min(stats.max_hp, stats.hp + delta.hp_change))

        # Apply XP changes
        if delta.xp_change != 0 and self.scenario.player.stats is not None:
            stats = self.scenario.player.stats
            stats.xp += delta.xp_change
            # Level up if XP threshold reached (simple: level * 100 XP)
            while stats.xp >= stats.level * 100:
                stats.xp -= stats.level * 100
                stats.level = min(20, stats.level + 1)
                stats.max_hp += 5
                stats.hp = stats.max_hp  # heal to full on level up

        # Move NPCs to scenes
        for move in delta.move_npc_to_scene:
            npc_id = move.get("npc_id", "")
            scene_id = move.get("scene_id", "")
            if npc_id in self.scenario.npcs:
                self.scenario.npcs[npc_id].current_scene = scene_id

        # Complete objectives (only in the current act)
        for obj_id in delta.complete_objectives:
            current_act = self._get_current_act()
            if current_act is not None and obj_id in current_act.objectives:
                current_act.objectives[obj_id].status = "complete"

        # Fail objectives (only in the current act)
        for obj_id in delta.fail_objectives:
            current_act = self._get_current_act()
            if current_act is not None and obj_id in current_act.objectives:
                current_act.objectives[obj_id].status = "failed"

        # Auto-complete objectives whose prerequisites are now met
        # ONLY in the current act — objectives in future acts should not be
        # auto-completed until the player reaches that act.
        player_flags = self.scenario.player.flags
        player_clues = set(self.scenario.player.clues)
        current_act = self._get_current_act()
        if current_act is not None:
            for obj in current_act.objectives.values():
                if obj.status != "active":
                    continue
                flags_met = all(flag in player_flags for flag in obj.required_flags)
                clues_met = all(clue in player_clues for clue in obj.required_clues)
                if flags_met and clues_met:
                    obj.status = "complete"

        # Auto-complete act flags when all objectives in an act are done
        # This is critical: without it, acts never progress and scenarios never end
        for act in self.scenario.acts.values():
            if not act.objectives:
                continue
            all_complete = all(obj.status in ("complete", "failed") for obj in act.objectives.values())
            if all_complete:
                for flag in act.completion_flags:
                    self.scenario.player.flags[flag] = True

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

    def _calculate_score_stats(self) -> Dict[str, int]:
        """Calculate score and completion statistics from current scenario state."""
        if self.scenario is None:
            return {
                "score": 0,
                "objectives_total": 0,
                "objectives_complete": 0,
                "clues_found": 0,
                "acts_total": 0,
                "acts_complete": 0,
            }

        objectives_total = 0
        objectives_complete = 0
        for act in self.scenario.acts.values():
            for obj in act.objectives.values():
                objectives_total += 1
                if obj.status == "complete":
                    objectives_complete += 1

        clues_found = len(self.scenario.player.clues)

        acts_total = len(self.scenario.acts)
        acts_complete = 0
        for act in self.scenario.acts.values():
            if all(flag in self.scenario.player.flags for flag in act.completion_flags):
                acts_complete += 1

        score = (objectives_complete * 100) + (clues_found * 50) + (acts_complete * 200)

        return {
            "score": score,
            "objectives_total": objectives_total,
            "objectives_complete": objectives_complete,
            "clues_found": clues_found,
            "acts_total": acts_total,
            "acts_complete": acts_complete,
        }

    def _check_act_progression(self) -> Optional[Dict[str, str]]:
        """Check if the current act is complete and advance or end the scenario.

        Returns a dict with 'transition' or 'ending' text if progression occurred.
        """
        if self.scenario is None:
            return None

        current_act = self._get_current_act()
        if current_act is None:
            return None

        flags_met = all(flag in self.scenario.player.flags for flag in current_act.completion_flags)
        if not flags_met:
            return None

        # Find ordered list of act IDs
        act_ids = sorted(self.scenario.acts.keys())
        try:
            current_index = act_ids.index(current_act.id)
        except ValueError:
            return None

        if current_index + 1 < len(act_ids):
            next_act_id = act_ids[current_index + 1]
            next_act = self.scenario.acts[next_act_id]
            self.scenario.player.current_act = next_act_id
            # Move player to the first scene of the next act
            if next_act.scenes:
                first_scene_id = sorted(next_act.scenes.keys())[0]
                # Runtime safety: ensure the new scene connects back to the
                # previous scene so the player isn't trapped
                prev_scene_id = self.scenario.player.current_scene
                if first_scene_id in next_act.scenes and prev_scene_id:
                    first_scene = next_act.scenes[first_scene_id]
                    if prev_scene_id not in first_scene.connected_scenes:
                        first_scene.connected_scenes.append(prev_scene_id)
                self.scenario.player.current_scene = first_scene_id
            return {
                "transition": (
                    f"--- {next_act.name} ---\n{next_act.description}"
                )
            }

        # Final act complete: scenario ending
        if current_act.ending_narration:
            return {"ending": current_act.ending_narration}

        return {"ending": "The story concludes. The world carries on, changed by your actions."}

    def _build_session_state_dict(self) -> Dict[str, Any]:
        """Build a serializable dict of the current session state for storage."""
        if self.scenario is None:
            return {
                "session_id": self.session_id,
                "turn_number": self.turn_number,
                "scenario_id": None,
            }

        return {
            "session_id": self.session_id,
            "turn_number": self.turn_number,
            "scenario_id": self.scenario_id,
            "scenario": self.scenario.model_dump(mode="json"),
        }
