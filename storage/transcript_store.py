"""Transcript storage module - stores interviews in structured formats."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from agents.interview import InterviewSession
from agents.analysis import TranscriptAnalysis, ThemeAnalysis


@dataclass
class StorageConfig:
    """Configuration for transcript storage."""

    base_path: Path
    study_name: str

    def __post_init__(self):
        self.base_path = Path(self.base_path)
        self.study_path = self.base_path / self.study_name
        self.transcripts_path = self.study_path / "transcripts"
        self.analyses_path = self.study_path / "analyses"
        self.rubrics_path = self.study_path / "rubrics"

        # Create directories
        for path in [
            self.transcripts_path,
            self.analyses_path,
            self.rubrics_path,
        ]:
            path.mkdir(parents=True, exist_ok=True)


class TranscriptStore:
    """Stores and retrieves interview transcripts and analyses."""

    def __init__(self, config: StorageConfig):
        self.config = config

    # -------------------------------------------------------------------------
    # Rubric Storage
    # -------------------------------------------------------------------------

    def save_rubric(self, rubric: dict, version: str = "v1") -> Path:
        """Save an interview rubric."""
        filename = f"rubric_{version}.json"
        path = self.config.rubrics_path / filename

        with open(path, "w") as f:
            json.dump(rubric, f, indent=2)

        return path

    def load_rubric(self, version: str = "v1") -> dict:
        """Load an interview rubric."""
        filename = f"rubric_{version}.json"
        path = self.config.rubrics_path / filename

        with open(path) as f:
            return json.load(f)

    # -------------------------------------------------------------------------
    # Transcript Storage
    # -------------------------------------------------------------------------

    def save_session(self, session: InterviewSession) -> Path:
        """Save an interview session as JSON."""
        filename = f"{session.session_id}.json"
        path = self.config.transcripts_path / filename

        with open(path, "w") as f:
            json.dump(session.to_dict(), f, indent=2, default=str)

        return path

    def load_session(self, session_id: str) -> InterviewSession:
        """Load an interview session from JSON."""
        filename = f"{session_id}.json"
        path = self.config.transcripts_path / filename

        with open(path) as f:
            data = json.load(f)

        return InterviewSession.from_dict(data)

    def list_sessions(self) -> list[str]:
        """List all session IDs."""
        return [p.stem for p in self.config.transcripts_path.glob("*.json")]

    def load_all_sessions(self) -> list[InterviewSession]:
        """Load all interview sessions."""
        sessions = []
        for session_id in self.list_sessions():
            sessions.append(self.load_session(session_id))
        return sessions

    # -------------------------------------------------------------------------
    # Analysis Storage
    # -------------------------------------------------------------------------

    def save_transcript_analysis(self, analysis: TranscriptAnalysis) -> Path:
        """Save individual transcript analysis."""
        filename = f"analysis_{analysis.transcript_id}.json"
        path = self.config.analyses_path / filename

        with open(path, "w") as f:
            json.dump(analysis.to_json(), f, indent=2)

        return path

    def save_theme_analysis(
        self, analysis: ThemeAnalysis, name: str = "themes"
    ) -> Path:
        """Save cross-transcript theme analysis."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.json"
        path = self.config.analyses_path / filename

        with open(path, "w") as f:
            json.dump(analysis.to_json(), f, indent=2)

        return path

    def load_theme_analysis(self, filename: str) -> ThemeAnalysis:
        """Load a theme analysis."""
        path = self.config.analyses_path / filename

        with open(path) as f:
            data = json.load(f)

        return ThemeAnalysis.from_json(data)

    # -------------------------------------------------------------------------
    # Parquet Export (for compatibility with Anthropic's format)
    # -------------------------------------------------------------------------

    def export_to_parquet(self, output_path: Path | None = None) -> Path:
        """Export all transcripts to Parquet format."""
        sessions = self.load_all_sessions()

        records = []
        for session in sessions:
            records.append(
                {
                    "transcript_id": session.session_id,
                    "participant_id": session.participant_id,
                    "text": session.get_transcript(),
                    "started_at": session.started_at.isoformat(),
                    "ended_at": session.ended_at.isoformat()
                    if session.ended_at
                    else None,
                    "message_count": len(session.messages),
                    "metadata": json.dumps(session.metadata),
                }
            )

        df = pd.DataFrame(records)
        table = pa.Table.from_pandas(df)

        output_path = output_path or (
            self.config.study_path / f"{self.config.study_name}_transcripts.parquet"
        )
        pq.write_table(table, output_path)

        return output_path

    def import_from_parquet(self, parquet_path: Path) -> list[dict]:
        """Import transcripts from Parquet format."""
        table = pq.read_table(parquet_path)
        df = table.to_pandas()
        return df.to_dict("records")

    # -------------------------------------------------------------------------
    # CSV Export
    # -------------------------------------------------------------------------

    def export_to_csv(self, output_path: Path | None = None) -> Path:
        """Export all transcripts to CSV format."""
        sessions = self.load_all_sessions()

        records = []
        for session in sessions:
            records.append(
                {
                    "transcript_id": session.session_id,
                    "participant_id": session.participant_id,
                    "text": session.get_transcript(),
                    "started_at": session.started_at.isoformat(),
                    "ended_at": session.ended_at.isoformat()
                    if session.ended_at
                    else None,
                    "message_count": len(session.messages),
                }
            )

        df = pd.DataFrame(records)

        output_path = output_path or (
            self.config.study_path / f"{self.config.study_name}_transcripts.csv"
        )
        df.to_csv(output_path, index=False)

        return output_path

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Get statistics about stored transcripts."""
        sessions = self.load_all_sessions()

        if not sessions:
            return {"total_sessions": 0}

        message_counts = [len(s.messages) for s in sessions]
        completed = [s for s in sessions if s.ended_at]

        return {
            "total_sessions": len(sessions),
            "completed_sessions": len(completed),
            "total_messages": sum(message_counts),
            "avg_messages_per_session": sum(message_counts) / len(sessions),
            "min_messages": min(message_counts),
            "max_messages": max(message_counts),
        }
