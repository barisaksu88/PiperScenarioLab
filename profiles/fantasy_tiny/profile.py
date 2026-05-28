"""Fantasy Tiny profile for PiperScenarioLab.

A lightweight fantasy RPG profile that allows dynamic flag creation
and focuses on narrative-driven scenarios with NPCs, clues, and
inventory management.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from scenario_engine.profile_base import ProfileBase


class FantasyTinyProfile(ProfileBase):
    """Profile for tiny fantasy adventure scenarios."""

    profile_id = "fantasy_tiny"
    display_name = "Tiny Fantasy"
    allowed_dynamic_creation = ["flags"]
    prompt_template_dir = "profiles/fantasy_tiny/prompts"
    ui_labels = {
        "acts_label": "Acts",
        "scenes_label": "Locations",
        "npcs_label": "Characters",
        "items_label": "Inventory",
        "skills_label": "Abilities",
        "clues_label": "Clues",
    }

    def get_validation_rules(self) -> Dict[str, Any]:
        """Return profile-specific validation rules.

        Fantasy scenarios allow dynamic flag creation (narrative state)
        and have a generous inventory limit for collecting items.
        """
        return {
            "allow_dynamic_flags": True,
            "max_inventory": 20,
        }

    def load_prompt(self, prompt_name: str) -> str:
        """Load a prompt template by name from the profile's prompt directory.

        Args:
            prompt_name: Name of the prompt file (e.g., 'narrator_turn.txt').

        Returns:
            The prompt template as a string.

        Raises:
            FileNotFoundError: If the prompt file does not exist.
        """
        template_path = os.path.join(self.prompt_template_dir, prompt_name)
        if not os.path.exists(template_path):
            raise FileNotFoundError(
                f"Prompt template not found: {template_path} "
                f"(looked for {prompt_name} in {self.prompt_template_dir})"
            )
        with open(template_path, encoding="utf-8") as f:
            return f.read()

    def get_state_extensions(self) -> Dict[str, Any]:
        """Return profile-specific state extension defaults.

        Fantasy scenarios have no special state extensions beyond the
        standard player state (flags, inventory, clues, skills).
        """
        return {}

    def check_dynamic_creation_allowed(self, entity_type: str) -> bool:
        """Check if profile allows dynamic creation of entity_type at runtime.

        Fantasy scenarios allow dynamic flag creation for narrative tracking.
        All other entity types (items, skills, NPCs, scenes) must be
        predefined in the scenario definition.
        """
        return entity_type in self.allowed_dynamic_creation
