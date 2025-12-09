"""Analysis Agent - extracts themes from interview transcripts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from anthropic import Anthropic

from prompts.analysis import (
    ANALYSIS_SYSTEM_PROMPT,
    SINGLE_TRANSCRIPT_PROMPT,
    CROSS_TRANSCRIPT_PROMPT,
)
from agents.interview import InterviewSession


@dataclass
class TranscriptAnalysis:
    """Analysis of a single transcript."""

    transcript_id: str
    summary: str
    key_codes: list[dict]
    notable_insights: list[str]
    research_question_relevance: dict
    raw_json: dict

    @classmethod
    def from_json(cls, data: dict) -> "TranscriptAnalysis":
        return cls(
            transcript_id=data.get("transcript_id", "unknown"),
            summary=data.get("summary", ""),
            key_codes=data.get("key_codes", []),
            notable_insights=data.get("notable_insights", []),
            research_question_relevance=data.get("research_question_relevance", {}),
            raw_json=data,
        )

    def to_json(self) -> dict:
        return self.raw_json


@dataclass
class ThemeAnalysis:
    """Cross-transcript theme analysis."""

    themes: list[dict]
    research_findings: list[dict]
    unexpected_discoveries: list[str]
    limitations: list[str]
    raw_json: dict

    @classmethod
    def from_json(cls, data: dict) -> "ThemeAnalysis":
        return cls(
            themes=data.get("themes", []),
            research_findings=data.get("research_findings", []),
            unexpected_discoveries=data.get("unexpected_discoveries", []),
            limitations=data.get("limitations", []),
            raw_json=data,
        )

    def to_json(self) -> dict:
        return self.raw_json

    def get_theme_summary(self) -> str:
        """Generate a readable summary of themes."""
        lines = ["# Theme Analysis Summary\n"]

        for i, theme in enumerate(self.themes, 1):
            lines.append(f"## Theme {i}: {theme.get('theme_name', 'Unnamed')}")
            lines.append(f"{theme.get('description', '')}")
            lines.append(f"**Prevalence**: {theme.get('prevalence', 'Unknown')}")
            if theme.get("sub_themes"):
                lines.append(f"**Sub-themes**: {', '.join(theme['sub_themes'])}")
            lines.append("")

        lines.append("# Key Findings\n")
        for finding in self.research_findings:
            lines.append(f"**{finding.get('research_question', 'RQ')}**")
            lines.append(f"{finding.get('finding', '')}")
            lines.append(f"*Confidence: {finding.get('confidence', 'unknown')}*\n")

        if self.unexpected_discoveries:
            lines.append("# Unexpected Discoveries\n")
            for discovery in self.unexpected_discoveries:
                lines.append(f"- {discovery}")

        return "\n".join(lines)


class AnalysisAgent:
    """Agent that analyzes interview transcripts and extracts themes."""

    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.client = client or Anthropic()
        self.model = model

    def analyze_transcript(
        self,
        session: InterviewSession,
        research_context: str,
        research_questions: list[str],
    ) -> TranscriptAnalysis:
        """Analyze a single interview transcript."""

        transcript = session.get_transcript()

        prompt = SINGLE_TRANSCRIPT_PROMPT.format(
            research_context=research_context,
            research_questions="\n".join(f"- {q}" for q in research_questions),
            transcript=transcript,
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text
        json_data = self._extract_json(response_text)

        # Ensure transcript_id is set
        json_data["transcript_id"] = session.session_id

        return TranscriptAnalysis.from_json(json_data)

    def analyze_themes(
        self,
        analyses: list[TranscriptAnalysis],
        research_context: str,
        research_questions: list[str],
    ) -> ThemeAnalysis:
        """Perform cross-transcript theme analysis."""

        # Format individual analyses for the prompt
        analyses_text = "\n\n---\n\n".join(
            f"### Transcript: {a.transcript_id}\n```json\n{json.dumps(a.to_json(), indent=2)}\n```"
            for a in analyses
        )

        prompt = CROSS_TRANSCRIPT_PROMPT.format(
            research_context=research_context,
            research_questions="\n".join(f"- {q}" for q in research_questions),
            transcript_analyses=analyses_text,
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text
        json_data = self._extract_json(response_text)

        return ThemeAnalysis.from_json(json_data)

    def batch_analyze(
        self,
        sessions: list[InterviewSession],
        research_context: str,
        research_questions: list[str],
    ) -> tuple[list[TranscriptAnalysis], ThemeAnalysis]:
        """Analyze multiple transcripts and synthesize themes."""

        # Step 1: Analyze each transcript individually
        individual_analyses = []
        for session in sessions:
            analysis = self.analyze_transcript(
                session, research_context, research_questions
            )
            individual_analyses.append(analysis)

        # Step 2: Synthesize themes across all transcripts
        theme_analysis = self.analyze_themes(
            individual_analyses, research_context, research_questions
        )

        return individual_analyses, theme_analysis

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from response text."""
        if "```json" in text:
            json_start = text.find("```json") + 7
            json_end = text.find("```", json_start)
            json_str = text[json_start:json_end].strip()
        elif "```" in text:
            json_start = text.find("```") + 3
            json_end = text.find("```", json_start)
            json_str = text[json_start:json_end].strip()
        else:
            # Try to find JSON object directly
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            json_str = text[json_start:json_end]

        return json.loads(json_str)
