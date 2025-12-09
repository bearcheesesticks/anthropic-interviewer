"""Interview Planning Agent - generates interview rubrics from research goals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from anthropic import Anthropic

from prompts.planning import PLANNING_SYSTEM_PROMPT, PLANNING_USER_TEMPLATE


@dataclass
class ResearchStudy:
    """Configuration for a research study."""

    research_goals: list[str]
    target_population: str
    hypotheses: Optional[list[str]] = None
    duration_minutes: int = 15
    format: str = "one-on-one conversational"
    additional_context: str = ""


@dataclass
class InterviewRubric:
    """Structured interview rubric output."""

    study_title: str
    research_goals: list[str]
    target_duration_minutes: int
    sections: list[dict]
    interviewer_guidance: dict
    raw_json: dict

    @classmethod
    def from_json(cls, data: dict) -> "InterviewRubric":
        return cls(
            study_title=data.get("study_title", "Untitled Study"),
            research_goals=data.get("research_goals", []),
            target_duration_minutes=data.get("target_duration_minutes", 15),
            sections=data.get("sections", []),
            interviewer_guidance=data.get("interviewer_guidance", {}),
            raw_json=data,
        )

    def get_all_questions(self) -> list[dict]:
        """Extract all questions from all sections."""
        questions = []
        for section in self.sections:
            questions.extend(section.get("questions", []))
        return questions

    def to_json(self) -> dict:
        return self.raw_json


class PlanningAgent:
    """Agent that creates interview rubrics from research goals."""

    def __init__(self, client: Anthropic | None = None, model: str = "claude-sonnet-4-20250514"):
        self.client = client or Anthropic()
        self.model = model

    def create_rubric(self, study: ResearchStudy) -> InterviewRubric:
        """Generate an interview rubric for the given study configuration."""

        user_prompt = PLANNING_USER_TEMPLATE.format(
            research_goals="\n".join(f"- {g}" for g in study.research_goals),
            target_population=study.target_population,
            hypotheses="\n".join(f"- {h}" for h in study.hypotheses)
            if study.hypotheses
            else "None specified - exploratory study",
            duration_minutes=study.duration_minutes,
            format=study.format,
            additional_context=study.additional_context or "None",
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=PLANNING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Extract JSON from response
        response_text = response.content[0].text

        # Handle potential markdown code blocks
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_str = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            json_str = response_text[json_start:json_end].strip()
        else:
            json_str = response_text.strip()

        rubric_data = json.loads(json_str)
        return InterviewRubric.from_json(rubric_data)

    def refine_rubric(
        self, rubric: InterviewRubric, feedback: str
    ) -> InterviewRubric:
        """Refine an existing rubric based on human feedback."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=PLANNING_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Here is an existing interview rubric:\n\n```json\n{json.dumps(rubric.to_json(), indent=2)}\n```\n\nPlease refine it based on this feedback:\n{feedback}\n\nOutput the complete revised rubric in JSON format.",
                }
            ],
        )

        response_text = response.content[0].text

        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_str = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            json_str = response_text[json_start:json_end].strip()
        else:
            json_str = response_text.strip()

        rubric_data = json.loads(json_str)
        return InterviewRubric.from_json(rubric_data)
