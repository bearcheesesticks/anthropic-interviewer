"""Analysis Service - Analyzes transcripts and extracts themes.

This service handles:
1. Individual transcript coding
2. Codebook development and management
3. Theme synthesis across transcripts
4. Research findings generation
"""

import json
from datetime import datetime
from typing import Optional

from anthropic import Anthropic
from sqlalchemy.orm import Session

from src.db.models import (
    Interview,
    Analysis,
    Code,
    Codebook,
    Theme,
    Study,
    StudyStatus,
)
from src.core.models import (
    TranscriptAnalysis,
    CodeCreate,
    ThemeCreate,
    ThemeSynthesis,
)


TRANSCRIPT_ANALYSIS_PROMPT = """Analyze this interview transcript for qualitative coding.

## Research Context
{research_context}

## Research Questions
{research_questions}

## Transcript
{transcript}

## Instructions

1. **Summarize** the transcript in 2-3 sentences
2. **Identify codes** - meaningful segments with descriptive labels
3. **Note insights** - unexpected or particularly valuable findings
4. **Map to research questions** - how does this transcript inform each RQ?

## Output Format
Return JSON:
```json
{{
    "summary": "2-3 sentence summary",
    "codes": [
        {{
            "code_name": "descriptive label",
            "code_description": "what this code captures",
            "quotation": "exact quote from transcript",
            "quotation_context": "surrounding context",
            "frequency": "single|multiple|pervasive",
            "confidence": 0.0-1.0
        }}
    ],
    "notable_insights": ["insight 1", "insight 2"],
    "research_question_relevance": {{
        "RQ1": "how this transcript informs RQ1",
        "RQ2": "how this transcript informs RQ2"
    }}
}}
```

Use EXACT quotations. Stay close to participant language."""


THEME_SYNTHESIS_PROMPT = """Synthesize themes across multiple transcript analyses.

## Research Context
{research_context}

## Research Questions
{research_questions}

## Individual Transcript Analyses
{analyses_summary}

## Instructions

1. **Identify themes** - patterns across transcripts
2. **Quantify prevalence** - how many transcripts mention each theme
3. **Answer research questions** - synthesize findings
4. **Note unexpected discoveries** - emergent insights
5. **Acknowledge limitations**

## Output Format
Return JSON:
```json
{{
    "themes": [
        {{
            "name": "theme name",
            "description": "what this theme captures",
            "code_names": ["codes that belong to this theme"],
            "prevalence_count": 8,
            "prevalence_percentage": 64.0,
            "example_quotations": ["quote1", "quote2"],
            "variation": "how this theme manifests differently"
        }}
    ],
    "research_findings": [
        {{
            "question": "RQ1 text",
            "finding": "synthesized answer",
            "confidence": "high|medium|low",
            "evidence_summary": "supporting evidence"
        }}
    ],
    "unexpected_discoveries": ["discovery 1"],
    "limitations": ["limitation 1"]
}}
```"""


class AnalysisService:
    """Service for analyzing transcripts and synthesizing themes."""

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
    # Individual Transcript Analysis
    # =========================================================================

    def analyze_transcript(
        self,
        interview: Interview,
        research_questions: Optional[list[str]] = None,
    ) -> TranscriptAnalysis:
        """Analyze a single interview transcript."""

        study = interview.study

        # Build context
        research_context = f"Study: {study.name}\nGoals: {'; '.join(study.research_goals)}"
        rqs = research_questions or [f"RQ{i+1}: {g}" for i, g in enumerate(study.research_goals)]

        prompt = TRANSCRIPT_ANALYSIS_PROMPT.format(
            research_context=research_context,
            research_questions="\n".join(f"- {q}" for q in rqs),
            transcript=interview.transcript,
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        data = self._extract_json(response.content[0].text)

        # Convert to domain model
        codes = [
            CodeCreate(
                code_name=c.get("code_name", "unnamed"),
                code_description=c.get("code_description"),
                quotation=c.get("quotation", ""),
                quotation_context=c.get("quotation_context"),
                frequency=c.get("frequency", "single"),
                confidence=c.get("confidence", 0.8),
            )
            for c in data.get("codes", [])
        ]

        return TranscriptAnalysis(
            interview_id=interview.id,
            summary=data.get("summary", ""),
            codes=codes,
            notable_insights=data.get("notable_insights", []),
            research_question_relevance=data.get("research_question_relevance", {}),
        )

    def save_analysis(self, analysis_data: TranscriptAnalysis) -> Analysis:
        """Save transcript analysis to database."""

        # Check if analysis exists
        existing = self.db.query(Analysis).filter(
            Analysis.interview_id == analysis_data.interview_id
        ).first()

        if existing:
            # Update existing
            existing.summary = analysis_data.summary
            existing.notable_insights = analysis_data.notable_insights
            existing.research_question_relevance = analysis_data.research_question_relevance
            existing.is_coded = True
            existing.coded_at = datetime.utcnow()

            # Remove old codes
            self.db.query(Code).filter(Code.analysis_id == existing.id).delete()

            analysis = existing
        else:
            # Create new
            analysis = Analysis(
                interview_id=analysis_data.interview_id,
                summary=analysis_data.summary,
                notable_insights=analysis_data.notable_insights,
                research_question_relevance=analysis_data.research_question_relevance,
                is_coded=True,
                coded_at=datetime.utcnow(),
            )
            self.db.add(analysis)

        self.db.flush()

        # Add codes
        for code_data in analysis_data.codes:
            code = Code(
                analysis_id=analysis.id,
                code_name=code_data.code_name,
                code_description=code_data.code_description,
                quotation=code_data.quotation,
                quotation_context=code_data.quotation_context,
                frequency=code_data.frequency,
                confidence=code_data.confidence,
            )
            self.db.add(code)

        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    # =========================================================================
    # Batch Analysis
    # =========================================================================

    def analyze_all_transcripts(
        self,
        study: Study,
        research_questions: Optional[list[str]] = None,
    ) -> list[TranscriptAnalysis]:
        """Analyze all completed interviews in a study."""

        interviews = self.db.query(Interview).filter(
            Interview.study_id == study.id,
            Interview.status == "completed",
        ).all()

        analyses = []
        for interview in interviews:
            analysis = self.analyze_transcript(interview, research_questions)
            self.save_analysis(analysis)
            analyses.append(analysis)

        return analyses

    # =========================================================================
    # Theme Synthesis
    # =========================================================================

    def synthesize_themes(
        self,
        study: Study,
        research_questions: Optional[list[str]] = None,
    ) -> ThemeSynthesis:
        """Synthesize themes across all analyzed transcripts."""

        # Get all analyses
        analyses = self.db.query(Analysis).join(Interview).filter(
            Interview.study_id == study.id,
            Analysis.is_coded == True,
        ).all()

        if not analyses:
            raise ValueError("No coded analyses found for this study")

        # Build analyses summary
        analyses_summary = []
        for a in analyses:
            codes_summary = ", ".join(c.code_name for c in a.codes[:10])
            analyses_summary.append(
                f"Interview {a.interview_id}: {a.summary}\nCodes: {codes_summary}"
            )

        research_context = f"Study: {study.name}\nGoals: {'; '.join(study.research_goals)}"
        rqs = research_questions or [f"RQ{i+1}: {g}" for i, g in enumerate(study.research_goals)]

        prompt = THEME_SYNTHESIS_PROMPT.format(
            research_context=research_context,
            research_questions="\n".join(f"- {q}" for q in rqs),
            analyses_summary="\n\n---\n\n".join(analyses_summary),
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )

        data = self._extract_json(response.content[0].text)

        # Convert to domain model
        themes = [
            ThemeCreate(
                name=t.get("name", "unnamed"),
                description=t.get("description", ""),
                code_names=t.get("code_names", []),
                example_quotations=t.get("example_quotations", []),
            )
            for t in data.get("themes", [])
        ]

        return ThemeSynthesis(
            themes=themes,
            research_findings=data.get("research_findings", []),
            unexpected_discoveries=data.get("unexpected_discoveries", []),
            limitations=data.get("limitations", []),
        )

    def save_theme_synthesis(
        self,
        study: Study,
        synthesis: ThemeSynthesis,
    ) -> Codebook:
        """Save theme synthesis as a codebook."""

        # Determine version
        existing = self.db.query(Codebook).filter(Codebook.study_id == study.id).count()
        version = existing + 1

        codebook = Codebook(
            study_id=study.id,
            version=version,
            is_active=True,
            is_locked=False,
        )
        self.db.add(codebook)
        self.db.flush()

        # Deactivate previous codebooks
        self.db.query(Codebook).filter(
            Codebook.study_id == study.id,
            Codebook.id != codebook.id,
        ).update({"is_active": False})

        # Add themes
        for theme_data in synthesis.themes:
            theme = Theme(
                codebook_id=codebook.id,
                name=theme_data.name,
                description=theme_data.description,
                code_names=theme_data.code_names,
                inclusion_criteria=theme_data.inclusion_criteria,
                exclusion_criteria=theme_data.exclusion_criteria,
                example_quotations=theme_data.example_quotations,
            )
            self.db.add(theme)

        # Update study status
        study.status = StudyStatus.ANALYSIS

        self.db.commit()
        self.db.refresh(codebook)
        return codebook

    # =========================================================================
    # Queries
    # =========================================================================

    def get_analysis(self, interview_id: int) -> Optional[Analysis]:
        """Get analysis for an interview."""
        return self.db.query(Analysis).filter(
            Analysis.interview_id == interview_id
        ).first()

    def get_codebook(self, study_id: int) -> Optional[Codebook]:
        """Get active codebook for a study."""
        return self.db.query(Codebook).filter(
            Codebook.study_id == study_id,
            Codebook.is_active == True,
        ).first()

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
