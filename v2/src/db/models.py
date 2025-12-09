"""SQLAlchemy database models for Anthropic Interviewer.

Database Schema:
    Study (1) ─────┬───── (N) Rubric
                   │           └── (N) RubricSection
                   │                    └── (N) RubricQuestion
                   │
                   ├───── (N) Interview
                   │           ├── (N) Message
                   │           │       └── (1) ProbeDecisionRecord

"""

from __future__ import annotations

"""
                   │           └── (1) Analysis
                   │                    └── (N) Code
                   │
                   └───── (N) Codebook
                              └── (N) Theme
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Enum,
    JSON,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


# =============================================================================
# Enums
# =============================================================================


class StudyStatus(PyEnum):
    """Status of a research study."""
    DRAFT = "draft"
    RUBRIC_REVIEW = "rubric_review"
    ACTIVE = "active"
    ANALYSIS = "analysis"
    COMPLETE = "complete"
    ARCHIVED = "archived"


class InterviewStatus(PyEnum):
    """Status of an interview session."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    ERROR = "error"


class ProbeAction(PyEnum):
    """Actions the probing engine can take."""
    PROBE_DEEPER = "probe_deeper"
    FOLLOW_UP = "follow_up"
    CLARIFY = "clarify"
    REFLECT = "reflect"
    MOVE_ON = "move_on"
    CIRCLE_BACK = "circle_back"
    REDIRECT = "redirect"
    CLOSE = "close"


class SignalType(PyEnum):
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


class MessageRole(PyEnum):
    """Role of a message in an interview."""
    INTERVIEWER = "interviewer"
    PARTICIPANT = "participant"
    SYSTEM = "system"


# =============================================================================
# Study & Rubric Models
# =============================================================================


class Study(Base):
    """A research study containing interviews and analysis."""

    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[StudyStatus] = mapped_column(Enum(StudyStatus), default=StudyStatus.DRAFT)

    # Research configuration
    research_goals: Mapped[list] = mapped_column(JSON, default=list)
    target_population: Mapped[Optional[str]] = mapped_column(Text)
    hypotheses: Mapped[Optional[list]] = mapped_column(JSON)
    target_duration_minutes: Mapped[int] = mapped_column(Integer, default=15)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    rubrics: Mapped[list["Rubric"]] = relationship(back_populates="study", cascade="all, delete-orphan")
    interviews: Mapped[list["Interview"]] = relationship(back_populates="study", cascade="all, delete-orphan")
    codebooks: Mapped[list["Codebook"]] = relationship(back_populates="study", cascade="all, delete-orphan")

    @property
    def active_rubric(self) -> Optional["Rubric"]:
        """Get the currently active rubric."""
        for rubric in self.rubrics:
            if rubric.is_active:
                return rubric
        return None


class Rubric(Base):
    """An interview rubric defining questions and structure."""

    __tablename__ = "rubrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)

    # Interviewer guidance
    guidance: Mapped[Optional[dict]] = mapped_column(JSON)  # tone, pacing, sensitive_topics, etc.

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    study: Mapped["Study"] = relationship(back_populates="rubrics")
    sections: Mapped[list["RubricSection"]] = relationship(
        back_populates="rubric", cascade="all, delete-orphan", order_by="RubricSection.order"
    )
    interviews: Mapped[list["Interview"]] = relationship(back_populates="rubric")

    __table_args__ = (
        Index("ix_rubric_study_version", "study_id", "version", unique=True),
    )


class RubricSection(Base):
    """A section within a rubric containing related questions."""

    __tablename__ = "rubric_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    rubric_id: Mapped[int] = mapped_column(ForeignKey("rubrics.id"), index=True)
    order: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[Optional[str]] = mapped_column(Text)
    transition_guidance: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    rubric: Mapped["Rubric"] = relationship(back_populates="sections")
    questions: Mapped[list["RubricQuestion"]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="RubricQuestion.order"
    )


class RubricQuestion(Base):
    """A question within a rubric section."""

    __tablename__ = "rubric_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("rubric_sections.id"), index=True)
    order: Mapped[int] = mapped_column(Integer)
    question_id: Mapped[str] = mapped_column(String(50))  # e.g., "Q1", "Q2a"
    text: Mapped[str] = mapped_column(Text)
    purpose: Mapped[Optional[str]] = mapped_column(Text)
    probes: Mapped[Optional[list]] = mapped_column(JSON)  # Follow-up probes
    required_depth: Mapped[int] = mapped_column(Integer, default=2)  # 1-3 scale
    skip_condition: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    section: Mapped["RubricSection"] = relationship(back_populates="questions")


# =============================================================================
# Interview Models
# =============================================================================


class Interview(Base):
    """An interview session with a participant."""

    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    rubric_id: Mapped[int] = mapped_column(ForeignKey("rubrics.id"), index=True)

    # Participant info
    participant_id: Mapped[str] = mapped_column(String(100), index=True)
    participant_context: Mapped[Optional[str]] = mapped_column(Text)

    # Session state
    status: Mapped[InterviewStatus] = mapped_column(
        Enum(InterviewStatus), default=InterviewStatus.IN_PROGRESS
    )

    # Conversation state (JSON blob for flexibility)
    conversation_state: Mapped[Optional[dict]] = mapped_column(JSON)

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Settings
    show_probing_analysis: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    study: Mapped["Study"] = relationship(back_populates="interviews")
    rubric: Mapped["Rubric"] = relationship(back_populates="interviews")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="interview", cascade="all, delete-orphan", order_by="Message.sequence"
    )
    analysis: Mapped[Optional["Analysis"]] = relationship(
        back_populates="interview", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_interview_study_participant", "study_id", "participant_id"),
    )

    @property
    def transcript(self) -> str:
        """Generate readable transcript."""
        lines = []
        for msg in self.messages:
            if msg.role == MessageRole.SYSTEM:
                continue
            speaker = "Interviewer" if msg.role == MessageRole.INTERVIEWER else "Participant"
            lines.append(f"{speaker}: {msg.content}")
        return "\n\n".join(lines)

    @property
    def duration_minutes(self) -> Optional[float]:
        """Calculate interview duration."""
        if self.ended_at:
            delta = self.ended_at - self.started_at
            return delta.total_seconds() / 60
        return None


class Message(Base):
    """A single message in an interview conversation."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)  # Order in conversation
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    interview: Mapped["Interview"] = relationship(back_populates="messages")
    probe_decision: Mapped[Optional["ProbeDecisionRecord"]] = relationship(
        back_populates="message", uselist=False, cascade="all, delete-orphan"
    )


class ProbeDecisionRecord(Base):
    """Record of a probing decision made during an interview."""

    __tablename__ = "probe_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), unique=True)

    # Decision
    action: Mapped[ProbeAction] = mapped_column(Enum(ProbeAction))
    reasoning: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    target_question_id: Mapped[Optional[str]] = mapped_column(String(50))

    # Signals detected (stored as JSON array)
    signals: Mapped[list] = mapped_column(JSON, default=list)
    # Each signal: {type: str, confidence: float, evidence: str}

    # State snapshot
    coverage_at_decision: Mapped[Optional[float]] = mapped_column(Float)
    depth_at_decision: Mapped[Optional[float]] = mapped_column(Float)
    time_remaining_at_decision: Mapped[Optional[float]] = mapped_column(Float)

    # Relationships
    message: Mapped["Message"] = relationship(back_populates="probe_decision")


# =============================================================================
# Analysis Models
# =============================================================================


class Analysis(Base):
    """Analysis of an individual interview transcript."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), unique=True)

    # Summary
    summary: Mapped[Optional[str]] = mapped_column(Text)
    notable_insights: Mapped[Optional[list]] = mapped_column(JSON)
    research_question_relevance: Mapped[Optional[dict]] = mapped_column(JSON)

    # Status
    is_coded: Mapped[bool] = mapped_column(Boolean, default=False)
    coded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    codebook_version: Mapped[Optional[int]] = mapped_column(Integer)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    interview: Mapped["Interview"] = relationship(back_populates="analysis")
    codes: Mapped[list["Code"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")


class Code(Base):
    """A code applied to a portion of a transcript."""

    __tablename__ = "codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), index=True)

    # Code info
    code_name: Mapped[str] = mapped_column(String(255), index=True)
    code_description: Mapped[Optional[str]] = mapped_column(Text)

    # Evidence
    quotation: Mapped[str] = mapped_column(Text)
    quotation_context: Mapped[Optional[str]] = mapped_column(Text)

    # Metadata
    frequency: Mapped[str] = mapped_column(String(50), default="single")  # single, multiple, pervasive
    confidence: Mapped[float] = mapped_column(Float, default=0.8)

    # Relationships
    analysis: Mapped["Analysis"] = relationship(back_populates="codes")


class Codebook(Base):
    """A codebook defining codes and themes for a study."""

    __tablename__ = "codebooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # No more changes after lock

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    study: Mapped["Study"] = relationship(back_populates="codebooks")
    themes: Mapped[list["Theme"]] = relationship(back_populates="codebook", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_codebook_study_version", "study_id", "version", unique=True),
    )


class Theme(Base):
    """A theme in a codebook, containing related codes."""

    __tablename__ = "themes"

    id: Mapped[int] = mapped_column(primary_key=True)
    codebook_id: Mapped[int] = mapped_column(ForeignKey("codebooks.id"), index=True)

    # Theme definition
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)

    # Codes belonging to this theme
    code_names: Mapped[list] = mapped_column(JSON, default=list)

    # Inclusion/exclusion criteria
    inclusion_criteria: Mapped[Optional[str]] = mapped_column(Text)
    exclusion_criteria: Mapped[Optional[str]] = mapped_column(Text)
    example_quotations: Mapped[Optional[list]] = mapped_column(JSON)

    # Prevalence (calculated)
    prevalence_count: Mapped[Optional[int]] = mapped_column(Integer)
    prevalence_percentage: Mapped[Optional[float]] = mapped_column(Float)

    # Sub-themes
    parent_theme_id: Mapped[Optional[int]] = mapped_column(ForeignKey("themes.id"))

    # Relationships
    codebook: Mapped["Codebook"] = relationship(back_populates="themes")
    sub_themes: Mapped[list["Theme"]] = relationship(back_populates="parent_theme")
    parent_theme: Mapped[Optional["Theme"]] = relationship(
        back_populates="sub_themes", remote_side=[id]
    )
