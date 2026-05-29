"""Storage layer for scenarios and sessions."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Scenario, SessionLogEntry


class Storage:
    def __init__(self, scenarios_dir: str = "scenarios", sessions_dir: str = "sessions"):
        self.scenarios_dir = Path(scenarios_dir)
        self.sessions_dir = Path(sessions_dir)
        self.scenarios_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def list_scenarios(self) -> List[Dict[str, str]]:
        """Return list of available scenario files with id and title."""
        scenarios = []
        if self.scenarios_dir.exists():
            for f in sorted(self.scenarios_dir.iterdir()):
                if f.suffix == ".json":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        metadata = data.get("metadata", {})
                        scenarios.append({
                            "id": f.stem,
                            "title": metadata.get("title", f.stem),
                            "description": metadata.get("description", "")
                        })
                    except Exception:
                        scenarios.append({"id": f.stem, "title": f.stem, "description": ""})
        return scenarios

    def load_scenario(self, scenario_id: str) -> Scenario:
        """Load a scenario definition from JSON."""
        path = self.scenarios_dir / f"{scenario_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Scenario not found: {scenario_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return Scenario.model_validate(data)

    def save_session(self, session_id: str, state: Dict[str, Any]) -> None:
        """Save session state to JSON."""
        path = self.sessions_dir / f"{session_id}.json"
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session state from JSON. Returns None if not found."""
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def session_exists(self, session_id: str) -> bool:
        """Check if a session file exists."""
        return (self.sessions_dir / f"{session_id}.json").exists()

    def append_log_entry(self, session_id: str, entry: SessionLogEntry) -> None:
        """Append a log entry to the session log."""
        log_path = self.sessions_dir / f"{session_id}_log.json"
        log_entries = []
        if log_path.exists():
            log_entries = json.loads(log_path.read_text(encoding="utf-8"))
        log_entries.append(entry.model_dump(mode="json"))
        log_path.write_text(json.dumps(log_entries, indent=2, default=str), encoding="utf-8")

    def load_session_log(self, session_id: str) -> List[SessionLogEntry]:
        """Load full session log."""
        log_path = self.sessions_dir / f"{session_id}_log.json"
        if not log_path.exists():
            return []
        entries = json.loads(log_path.read_text(encoding="utf-8"))
        return [SessionLogEntry.model_validate(e) for e in entries]

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Return list of saved sessions with metadata."""
        sessions = []
        if self.sessions_dir.exists():
            for f in sorted(self.sessions_dir.iterdir()):
                if f.suffix == ".json" and not f.name.endswith("_log.json"):
                    # Skip harness / test sessions
                    if f.name.startswith("harness_"):
                        continue
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        sessions.append({
                            "session_id": data.get("session_id", f.stem),
                            "scenario_id": data.get("scenario_id"),
                            "turn_number": data.get("turn_number", 0),
                            "scenario_title": (
                                data.get("scenario", {}).get("metadata", {}).get("title", "Unknown")
                                if isinstance(data.get("scenario"), dict)
                                else "Unknown"
                            ),
                            "updated_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                        })
                    except Exception:
                        sessions.append({"session_id": f.stem, "scenario_id": None, "turn_number": 0, "scenario_title": "Unknown", "updated_at": ""})
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its log. Returns True if anything was deleted."""
        deleted = False
        for path in [self.sessions_dir / f"{session_id}.json", self.sessions_dir / f"{session_id}_log.json"]:
            if path.exists():
                path.unlink()
                deleted = True
        return deleted

    def generate_session_id(self) -> str:
        """Generate unique session ID."""
        return f"sess_{uuid.uuid4().hex[:12]}"
