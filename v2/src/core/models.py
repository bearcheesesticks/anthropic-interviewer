"""Pydantic models for the core domain.

These models are used for:
- API request/response validation
- Service layer communication
- Configuration
- Serialization

They are separate from SQLAlchemy models to maintain clean separation.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums (mirrored from db.models for use without DB dependency)
# =============================================================================


class SignalType(str, Enum):
    """Types of signals detected in participant responses."""
    NOVELTY = "novelty"
    VAGUENESS = "vagueness"
    EMOTION = "emotion"
    CONTRADICTION = "contradiction"
    REPETITION = "repetition"
    BREVITY = "brevity"
    DISCOMFORT = "discomfort"
    ENTHUSIASM = "enthusiasm"
    TANGENT = "tangent"
    COMPLETION = "completion"


class ProbeAction(str, Enum):
    """Actions the probing engine can take."""
    PROBE_DEEPER = "probe_deeper"
    FOLLOW_UP = "follow_up"
    CLARIFY = "clarify"
    REFLECT = "reflect"
    MOVE_ON = "move_on"
    CIRCLE_BACK = "circle_back"
    REDIRECT = "redirect"
    CLOSE = "close"


class MessageRole(str, Enum):
    """Role of a message in an interview."""
    INTERVIEWER = "interviewer"
    PARTICIPANT = "participant"
    SYSTEM = "system"


class StudyStatus(str, Enum):
    """Status of a research study."""
    DRAFT = "draft"
    RUBRIC_REVIEW = "rubric_review"
    ACTIVE = "active"
    ANALYSIS = "analysis"
    COMPLETE = "complete"


class InterviewStatus(str, Enum):
    """Status of an interview session."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    ERROR = "error"


# =============================================================================
# Study & Rubric Models
# =============================================================================


class StudyConfig(BaseModel):
    """Configuration for creating a new study."""
    name: str
    description: Optional[str] = None
    research_goals: list[str]
    target_population: str
    hypotheses: Optional[list[str]] = None
    target_duration_minutes: int = 15
    additional_context: Optional[str] = None


class InterviewerGuidance(BaseModel):
    """Guidance for the interviewer agent."""
    tone: str = "Warm, curious, non-judgmental"
    pacing: str = "Allow silence for reflection, don't rush"
    sensitive_topics: list[str] = Field(default_factory=list)
    probing_strategy: str = "Prioritize concrete examples over abstract opinions"
    closing_approach: str = "Always offer chance to add anything not covered"


class QuestionConfig(BaseModel):
    """Configuration for a single interview question."""
    question_id: str
    text: str
    purpose: Optional[str] = None
    probes: list[str] = Field(default_factory=list)
    required_depth: int = Field(default=2, ge=1, le=3)
    skip_condition: Optional[str] = None


class SectionConfig(BaseModel):
    """Configuration for a rubric section."""
    name: str
    purpose: Optional[str] = None
    questions: list[QuestionConfig]
    transition_guidance: Optional[str] = None


class RubricCreate(BaseModel):
    """Data for creating a new rubric."""
    title: str
    sections: list[SectionConfig]
    guidance: InterviewerGuidance = Field(default_factory=InterviewerGuidance)


class RubricResponse(BaseModel):
    """Rubric data returned from API."""
    id: int
    study_id: int
    version: int
    title: str
    sections: list[SectionConfig]
    guidance: InterviewerGuidance
    is_active: bool
    is_approved: bool
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Interview Models
# =============================================================================


class InterviewConfig(BaseModel):
    """Configuration for starting an interview."""
    participant_id: str
    participant_context: Optional[str] = None
    show_probing_analysis: bool = False


class MessageCreate(BaseModel):
    """Data for creating a new message."""
    role: MessageRole
    content: str


class MessageResponse(BaseModel):
    """Message data returned from API."""
    id: int
    sequence: int
    role: MessageRole
    content: str
    timestamp: datetime
    probe_decision: Optional["ProbeDecisionResponse"] = None

    class Config:
        from_attributes = True


class InterviewState(BaseModel):
    """Current state of an interview for API responses."""
    id: int
    status: InterviewStatus
    participant_id: str
    message_count: int
    duration_minutes: Optional[float]
    coverage: Optional[float]
    average_depth: Optional[float]
    time_remaining: Optional[float]
    started_at: datetime
    ended_at: Optional[datetime]


# =============================================================================
# Probing Models
# =============================================================================


class Signal(BaseModel):
    """A signal detected in a participant response."""
    signal_type: SignalType
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str


class ProbeDecision(BaseModel):
    """Decision made by the probing engine."""
    action: ProbeAction
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    signals: list[Signal] = Field(default_factory=list)
    suggested_probe: Optional[str] = None
    target_question_id: Optional[str] = None


class ProbeDecisionResponse(BaseModel):
    """Probe decision data returned from API."""
    action: ProbeAction
    reasoning: str
    confidence: float
    signals: list[Signal]

    class Config:
        from_attributes = True


class TopicState(BaseModel):
    """State tracking for a single topic/question."""
    question_id: str
    question_text: str
    times_addressed: int = 0
    depth_achieved: int = 0  # 0-3
    key_points: list[str] = Field(default_factory=list)
    needs_revisit: bool = False
    revisit_reason: Optional[str] = None


class ConversationState(BaseModel):
    """Full state of the interview conversation."""
    topics: dict[str, TopicState] = Field(default_factory=dict)
    current_topic_id: Optional[str] = None
    messages_count: int = 0
    estimated_minutes_elapsed: float = 0.0
    target_duration_minutes: int = 15
    themes_emerged: list[str] = Field(default_factory=list)
    items_to_circle_back: list[dict] = Field(default_factory=list)
    participant_style: str = "unknown"
    earlier_statements: list[str] = Field(default_factory=list)
    # Track recent interviewer questions to avoid repetition (compact summaries)
    recent_questions_asked: list[str] = Field(default_factory=list)

    def time_remaining(self) -> float:
        """Calculate remaining time."""
        return max(0, self.target_duration_minutes - self.estimated_minutes_elapsed)

    def coverage_ratio(self) -> float:
        """Calculate topic coverage ratio."""
        if not self.topics:
            return 0.0
        addressed = sum(1 for t in self.topics.values() if t.times_addressed > 0)
        return addressed / len(self.topics)

    def average_depth(self) -> float:
        """Calculate average depth across addressed topics."""
        addressed = [t for t in self.topics.values() if t.times_addressed > 0]
        if not addressed:
            return 0.0
        return sum(t.depth_achieved for t in addressed) / len(addressed)


# =============================================================================
# Analysis Models
# =============================================================================


class CodeCreate(BaseModel):
    """Data for creating a code applied to a transcript."""
    code_name: str
    code_description: Optional[str] = None
    quotation: str
    quotation_context: Optional[str] = None
    frequency: str = "single"  # single, multiple, pervasive
    confidence: float = 0.8


class TranscriptAnalysis(BaseModel):
    """Analysis of a single transcript."""
    interview_id: int
    summary: str
    codes: list[CodeCreate]
    notable_insights: list[str] = Field(default_factory=list)
    research_question_relevance: dict[str, str] = Field(default_factory=dict)


class ThemeCreate(BaseModel):
    """Data for creating a theme."""
    name: str
    description: str
    code_names: list[str]
    inclusion_criteria: Optional[str] = None
    exclusion_criteria: Optional[str] = None
    example_quotations: list[str] = Field(default_factory=list)


class ThemeSynthesis(BaseModel):
    """Cross-transcript theme synthesis results."""
    themes: list[ThemeCreate]
    research_findings: list[dict]  # {question, finding, confidence, evidence}
    unexpected_discoveries: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# Update forward references
MessageResponse.model_rebuild()
