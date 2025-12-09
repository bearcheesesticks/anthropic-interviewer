"""Planning Service - Creates and manages interview rubrics."""

from __future__ import annotations

import json
from typing import Optional

from anthropic import Anthropic
from sqlalchemy.orm import Session

from src.db.models import Study, Rubric, RubricSection, RubricQuestion, StudyStatus
from src.core.models import StudyConfig, RubricCreate, SectionConfig, QuestionConfig, InterviewerGuidance


RUBRIC_GENERATION_PROMPT = """You are an expert qualitative researcher. Create an interview rubric for this study.

## Research Study Configuration

**Research Goals:**
{research_goals}

**Target Population:** {target_population}

**Hypotheses:**
{hypotheses}

**Target Duration:** {duration} minutes

**Additional Context:**
{additional_context}

## Rubric Requirements

Create a structured interview rubric with:

1. **5-8 sections** covering different aspects of the research goals
2. **1-2 questions per section** (depth over breadth)
3. **2-3 probes per question** for follow-up
4. **Clear interviewer guidance** for tone, pacing, sensitive topics

## Question Design Principles

- Use open-ended questions (how, what, describe, tell me about)
- Avoid leading questions
- Start broad, then narrow to specifics
- Include behavioral questions (what they DO) not just opinions
- Build questions to flow naturally

## Output Format

Return a JSON object:
```json
{{
    "title": "Study title",
    "sections": [
        {{
            "name": "Section name",
            "purpose": "Why this section matters",
            "questions": [
                {{
                    "question_id": "Q1",
                    "text": "The actual question",
                    "purpose": "What this question aims to uncover",
                    "probes": ["Follow-up 1", "Follow-up 2"],
                    "required_depth": 2
                }}
            ],
            "transition_guidance": "How to transition to next section"
        }}
    ],
    "guidance": {{
        "tone": "Overall interviewer tone",
        "pacing": "Guidance on pacing",
        "sensitive_topics": ["topic1", "topic2"],
        "probing_strategy": "When and how to probe deeper",
        "closing_approach": "How to wrap up"
    }}
}}
```"""


class PlanningService:
    """Service for creating and managing studies and rubrics."""

    def __init__(
        self,
        db: Session,
        client: Optional[Anthropic] = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.db = db
        self.client = client or Anthropic()
        self.model = model

    # =========================================================================
    # Study Management
    # =========================================================================

    def create_study(self, config: StudyConfig) -> Study:
        """Create a new research study."""
        study = Study(
            name=config.name,
            description=config.description,
            research_goals=config.research_goals,
            target_population=config.target_population,
            hypotheses=config.hypotheses,
            target_duration_minutes=config.target_duration_minutes,
            status=StudyStatus.DRAFT,
        )
        self.db.add(study)
        self.db.commit()
        self.db.refresh(study)
        return study

    def get_study(self, study_id: int) -> Optional[Study]:
        """Get a study by ID."""
        return self.db.query(Study).filter(Study.id == study_id).first()

    def get_study_by_name(self, name: str) -> Optional[Study]:
        """Get a study by name."""
        return self.db.query(Study).filter(Study.name == name).first()

    def list_studies(self) -> list[Study]:
        """List all studies."""
        return self.db.query(Study).order_by(Study.created_at.desc()).all()

    def update_study_status(self, study_id: int, status: StudyStatus) -> Study:
        """Update study status."""
        study = self.get_study(study_id)
        if not study:
            raise ValueError(f"Study {study_id} not found")
        study.status = status
        self.db.commit()
        return study

    # =========================================================================
    # Rubric Generation
    # =========================================================================

    def generate_rubric(self, study: Study) -> RubricCreate:
        """Generate a rubric for a study using LLM."""

        prompt = RUBRIC_GENERATION_PROMPT.format(
            research_goals="\n".join(f"- {g}" for g in study.research_goals),
            target_population=study.target_population,
            hypotheses="\n".join(f"- {h}" for h in (study.hypotheses or []))
            if study.hypotheses else "None specified (exploratory study)",
            duration=study.target_duration_minutes,
            additional_context=study.description or "None provided",
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text
        data = self._extract_json(response_text)

        # Convert to RubricCreate
        sections = []
        for section_data in data.get("sections", []):
            questions = []
            for q_data in section_data.get("questions", []):
                questions.append(QuestionConfig(
                    question_id=q_data.get("question_id", f"Q{len(questions)+1}"),
                    text=q_data.get("text", ""),
                    purpose=q_data.get("purpose"),
                    probes=q_data.get("probes", []),
                    required_depth=q_data.get("required_depth", 2),
                    skip_condition=q_data.get("skip_condition"),
                ))

            sections.append(SectionConfig(
                name=section_data.get("name", "Unnamed Section"),
                purpose=section_data.get("purpose"),
                questions=questions,
                transition_guidance=section_data.get("transition_guidance"),
            ))

        guidance_data = data.get("guidance", {})
        guidance = InterviewerGuidance(
            tone=guidance_data.get("tone", "Warm, curious, non-judgmental"),
            pacing=guidance_data.get("pacing", "Allow silence for reflection"),
            sensitive_topics=guidance_data.get("sensitive_topics", []),
            probing_strategy=guidance_data.get("probing_strategy", "Prioritize examples"),
            closing_approach=guidance_data.get("closing_approach", "Offer chance to add more"),
        )

        return RubricCreate(
            title=data.get("title", f"Rubric for {study.name}"),
            sections=sections,
            guidance=guidance,
        )

    def save_rubric(self, study: Study, rubric_data: RubricCreate) -> Rubric:
        """Save a generated rubric to the database."""

        # Determine version number
        existing_versions = self.db.query(Rubric).filter(Rubric.study_id == study.id).count()
        version = existing_versions + 1

        # Create rubric
        rubric = Rubric(
            study_id=study.id,
            version=version,
            title=rubric_data.title,
            is_active=False,
            is_approved=False,
            guidance=rubric_data.guidance.model_dump(),
        )
        self.db.add(rubric)
        self.db.flush()  # Get rubric.id

        # Create sections and questions
        for section_order, section_data in enumerate(rubric_data.sections):
            section = RubricSection(
                rubric_id=rubric.id,
                order=section_order,
                name=section_data.name,
                purpose=section_data.purpose,
                transition_guidance=section_data.transition_guidance,
            )
            self.db.add(section)
            self.db.flush()

            for q_order, q_data in enumerate(section_data.questions):
                question = RubricQuestion(
                    section_id=section.id,
                    order=q_order,
                    question_id=q_data.question_id,
                    text=q_data.text,
                    purpose=q_data.purpose,
                    probes=q_data.probes,
                    required_depth=q_data.required_depth,
                    skip_condition=q_data.skip_condition,
                )
                self.db.add(question)

        self.db.commit()
        self.db.refresh(rubric)
        return rubric

    def approve_rubric(self, rubric_id: int) -> Rubric:
        """Approve a rubric and make it active."""
        rubric = self.db.query(Rubric).filter(Rubric.id == rubric_id).first()
        if not rubric:
            raise ValueError(f"Rubric {rubric_id} not found")

        # Deactivate other rubrics for this study
        self.db.query(Rubric).filter(
            Rubric.study_id == rubric.study_id,
            Rubric.id != rubric_id,
        ).update({"is_active": False})

        # Activate and approve this one
        rubric.is_active = True
        rubric.is_approved = True
        rubric.approved_at = __import__("datetime").datetime.utcnow()

        # Update study status
        rubric.study.status = StudyStatus.ACTIVE

        self.db.commit()
        return rubric

    def get_rubric(self, rubric_id: int) -> Optional[Rubric]:
        """Get a rubric by ID."""
        return self.db.query(Rubric).filter(Rubric.id == rubric_id).first()

    def get_active_rubric(self, study_id: int) -> Optional[Rubric]:
        """Get the active rubric for a study."""
        return self.db.query(Rubric).filter(
            Rubric.study_id == study_id,
            Rubric.is_active == True,
        ).first()

    def rubric_to_sections(self, rubric: Rubric) -> list[SectionConfig]:
        """Convert a database rubric to SectionConfig list."""
        sections = []
        for section in rubric.sections:
            questions = []
            for q in section.questions:
                questions.append(QuestionConfig(
                    question_id=q.question_id,
                    text=q.text,
                    purpose=q.purpose,
                    probes=q.probes or [],
                    required_depth=q.required_depth,
                    skip_condition=q.skip_condition,
                ))
            sections.append(SectionConfig(
                name=section.name,
                purpose=section.purpose,
                questions=questions,
                transition_guidance=section.transition_guidance,
            ))
        return sections

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response."""
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            json_str = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            json_str = text[start:end].strip()
        else:
            start = text.find("{")
            end = text.rfind("}") + 1
            json_str = text[start:end]

        return json.loads(json_str)
