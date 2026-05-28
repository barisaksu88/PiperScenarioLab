"""Abstract base class for scenario profiles."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ProfileBase(ABC):
    """Abstract base class for scenario profiles."""

    profile_id: str = ""
    display_name: str = ""
    allowed_dynamic_creation: List[str] = []
    prompt_template_dir: str = ""
    ui_labels: Dict[str, str] = {}

    @abstractmethod
    def get_validation_rules(self) -> Dict[str, Any]:
        """Return profile-specific validation rules."""
        pass

    @abstractmethod
    def load_prompt(self, prompt_name: str) -> str:
        """Load a prompt template by name."""
        pass

    @abstractmethod
    def get_state_extensions(self) -> Dict[str, Any]:
        """Return profile-specific state extension defaults."""
        pass

    @abstractmethod
    def check_dynamic_creation_allowed(self, entity_type: str) -> bool:
        """Check if profile allows dynamic creation of entity_type."""
        pass
