"""Flight Training profile for PiperScenarioLab.

A placeholder profile for aviation training scenarios. This profile
is designed for procedural training simulations involving aircraft
systems, ATC communication, checklist management, and emergency
procedures.

NOTE: This is a placeholder profile. No real SOPs or proprietary
procedures are encoded here.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from scenario_engine.profile_base import ProfileBase


class FlightTrainingProfile(ProfileBase):
    """Profile for flight training simulation scenarios."""

    profile_id = "flight_training"
    display_name = "Flight Training (Placeholder)"
    allowed_dynamic_creation: List[str] = []
    prompt_template_dir = "profiles/flight_training/prompts"
    ui_labels = {
        "acts_label": "Phases",
        "scenes_label": "Situations",
        "npcs_label": "Crew / ATC",
        "items_label": "Systems",
        "skills_label": "Procedures",
        "clues_label": "Indications",
    }

    def get_validation_rules(self) -> Dict[str, Any]:
        """Return profile-specific validation rules.

        Flight training scenarios do NOT allow dynamic creation of any
        entity type. All items, skills, flags, etc. must be predefined
        in the scenario definition for training consistency and safety.
        """
        return {
            "allow_dynamic_flags": False,
        }

    def load_prompt(self, prompt_name: str) -> str:
        """Load a prompt template by name from the profile's prompt directory.

        If the requested prompt file does not exist, returns a placeholder
        message indicating the prompt is not yet implemented.

        Args:
            prompt_name: Name of the prompt file.

        Returns:
            The prompt template as a string, or a placeholder message.
        """
        template_path = os.path.join(self.prompt_template_dir, prompt_name)
        if not os.path.exists(template_path):
            return (
                f"# PLACEHOLDER: {prompt_name}\n\n"
                f"# Flight training prompts are not yet implemented.\n"
                f"# This profile is a placeholder scaffold.\n"
                f"# Expected file: {template_path}\n"
            )
        with open(template_path, encoding="utf-8") as f:
            return f.read()

    def get_state_extensions(self) -> Dict[str, Any]:
        """Return profile-specific state extension defaults.

        Flight training scenarios track additional state beyond the
        standard player state, including aircraft configuration,
        flight phase, weather conditions, system failures, checklists,
        ATC communications, and grading information.

        These extensions are stored in the Scenario.extensions dict
        and managed by the engine during turn processing.
        """
        return {
            "aircraft": {
                "type": "",
                "registration": "",
            },
            "phase_of_flight": "",
            "weather": {
                "condition": "",
                "visibility": 0,
                "wind": "",
            },
            "failures": [],
            "checklists": [],
            "atc_comms": [],
            "grading": {
                "score": 0,
                "notes": [],
            },
        }

    def check_dynamic_creation_allowed(self, entity_type: str) -> bool:
        """Check if profile allows dynamic creation of entity_type at runtime.

        Flight training scenarios never allow dynamic creation. All
        entities must be predefined to ensure training consistency.
        """
        return False
