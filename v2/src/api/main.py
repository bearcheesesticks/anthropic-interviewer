"""FastAPI application for Anthropic Interviewer."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.session import init_db, get_db
from src.db.models import StudyStatus, InterviewStatus
from src.services import PlanningService, InterviewService, AnalysisService
from src.core.models import (
    StudyConfig,
    InterviewConfig,
    ProbeDecision,
    InterviewState,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    init_db()
    yield


app = FastAPI(
    title="Anthropic Interviewer",
    description="AI-powered qualitative research interviews",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_anthropic_client():
    """Get Anthropic client with API key from environment."""
    from anthropic import Anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")
    return Anthropic(api_key=api_key)


# =============================================================================
# Request/Response Models
# =============================================================================


class StudyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    research_goals: list[str]
    target_population: str
    hypotheses: Optional[list[str]] = None
    target_duration_minutes: int = 15


class StudyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    status: str
    research_goals: list[str]
    target_population: Optional[str]
    target_duration_minutes: int
    rubric_count: int
    interview_count: int

    class Config:
        from_attributes = True


class RubricSummary(BaseModel):
    id: int
    version: int
    title: str
    is_active: bool
    is_approved: bool
    section_count: int
    question_count: int


class QuestionResponse(BaseModel):
    question_id: str
    text: str
    purpose: Optional[str]
    probes: list[str]


class SectionResponse(BaseModel):
    name: str
    purpose: Optional[str]
    questions: list[QuestionResponse]


class RubricDetail(BaseModel):
    id: int
    version: int
    title: str
    is_active: bool
    is_approved: bool
    sections: list[SectionResponse]
    guidance: Optional[dict]


class InterviewStart(BaseModel):
    participant_id: str
    participant_context: Optional[str] = None


class InterviewResponse(BaseModel):
    id: int
    participant_id: str
    status: str
    message_count: int
    started_at: str


class MessageResponse(BaseModel):
    role: str
    content: str
    probe_decision: Optional[dict] = None


class ConversationResponse(BaseModel):
    interview_id: int
    status: str
    messages: list[MessageResponse]
    state: Optional[dict] = None


class ParticipantMessage(BaseModel):
    message: str


class InterviewerResponse(BaseModel):
    message: str
    probe_decision: Optional[dict] = None
    is_complete: bool = False


# =============================================================================
# Study Endpoints
# =============================================================================


@app.get("/api/studies", response_model=list[StudyResponse])
def list_studies(db: Session = Depends(get_db)):
    """List all studies."""
    client = get_anthropic_client()
    service = PlanningService(db, client)
    studies = service.list_studies()

    return [
        StudyResponse(
            id=s.id,
            name=s.name,
            description=s.description,
            status=s.status.value,
            research_goals=s.research_goals,
            target_population=s.target_population,
            target_duration_minutes=s.target_duration_minutes,
            rubric_count=len(s.rubrics),
            interview_count=len(s.interviews),
        )
        for s in studies
    ]


@app.post("/api/studies", response_model=StudyResponse)
def create_study(data: StudyCreate, db: Session = Depends(get_db)):
    """Create a new study."""
    client = get_anthropic_client()
    service = PlanningService(db, client)

    config = StudyConfig(
        name=data.name,
        description=data.description,
        research_goals=data.research_goals,
        target_population=data.target_population,
        hypotheses=data.hypotheses,
        target_duration_minutes=data.target_duration_minutes,
    )

    study = service.create_study(config)

    return StudyResponse(
        id=study.id,
        name=study.name,
        description=study.description,
        status=study.status.value,
        research_goals=study.research_goals,
        target_population=study.target_population,
        target_duration_minutes=study.target_duration_minutes,
        rubric_count=0,
        interview_count=0,
    )


@app.get("/api/studies/{study_id}", response_model=StudyResponse)
def get_study(study_id: int, db: Session = Depends(get_db)):
    """Get a study by ID."""
    client = get_anthropic_client()
    service = PlanningService(db, client)
    study = service.get_study(study_id)

    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    return StudyResponse(
        id=study.id,
        name=study.name,
        description=study.description,
        status=study.status.value,
        research_goals=study.research_goals,
        target_population=study.target_population,
        target_duration_minutes=study.target_duration_minutes,
        rubric_count=len(study.rubrics),
        interview_count=len(study.interviews),
    )


# =============================================================================
# Rubric Endpoints
# =============================================================================


@app.get("/api/studies/{study_id}/rubrics", response_model=list[RubricSummary])
def list_rubrics(study_id: int, db: Session = Depends(get_db)):
    """List rubrics for a study."""
    client = get_anthropic_client()
    service = PlanningService(db, client)
    study = service.get_study(study_id)

    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    return [
        RubricSummary(
            id=r.id,
            version=r.version,
            title=r.title,
            is_active=r.is_active,
            is_approved=r.is_approved,
            section_count=len(r.sections),
            question_count=sum(len(s.questions) for s in r.sections),
        )
        for r in study.rubrics
    ]


@app.post("/api/studies/{study_id}/rubrics/generate", response_model=RubricDetail)
def generate_rubric(study_id: int, db: Session = Depends(get_db)):
    """Generate a new rubric for a study."""
    client = get_anthropic_client()
    service = PlanningService(db, client)
    study = service.get_study(study_id)

    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    rubric_data = service.generate_rubric(study)
    rubric = service.save_rubric(study, rubric_data)

    return _rubric_to_detail(rubric)


@app.get("/api/rubrics/{rubric_id}", response_model=RubricDetail)
def get_rubric(rubric_id: int, db: Session = Depends(get_db)):
    """Get rubric details."""
    client = get_anthropic_client()
    service = PlanningService(db, client)
    rubric = service.get_rubric(rubric_id)

    if not rubric:
        raise HTTPException(status_code=404, detail="Rubric not found")

    return _rubric_to_detail(rubric)


@app.post("/api/rubrics/{rubric_id}/approve", response_model=RubricDetail)
def approve_rubric(rubric_id: int, db: Session = Depends(get_db)):
    """Approve a rubric for use."""
    client = get_anthropic_client()
    service = PlanningService(db, client)

    try:
        rubric = service.approve_rubric(rubric_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return _rubric_to_detail(rubric)


def _rubric_to_detail(rubric) -> RubricDetail:
    """Convert rubric to detail response."""
    sections = []
    for section in rubric.sections:
        questions = [
            QuestionResponse(
                question_id=q.question_id,
                text=q.text,
                purpose=q.purpose,
                probes=q.probes or [],
            )
            for q in section.questions
        ]
        sections.append(SectionResponse(
            name=section.name,
            purpose=section.purpose,
            questions=questions,
        ))

    return RubricDetail(
        id=rubric.id,
        version=rubric.version,
        title=rubric.title,
        is_active=rubric.is_active,
        is_approved=rubric.is_approved,
        sections=sections,
        guidance=rubric.guidance,
    )


# =============================================================================
# Interview Endpoints
# =============================================================================


@app.get("/api/studies/{study_id}/interviews", response_model=list[InterviewResponse])
def list_interviews(study_id: int, db: Session = Depends(get_db)):
    """List interviews for a study."""
    client = get_anthropic_client()
    service = InterviewService(db, client)
    interviews = service.list_interviews(study_id)

    return [
        InterviewResponse(
            id=i.id,
            participant_id=i.participant_id,
            status=i.status.value,
            message_count=len(i.messages),
            started_at=i.started_at.isoformat(),
        )
        for i in interviews
    ]


@app.post("/api/studies/{study_id}/interviews", response_model=ConversationResponse)
def start_interview(
    study_id: int,
    data: InterviewStart,
    db: Session = Depends(get_db),
):
    """Start a new interview."""
    client = get_anthropic_client()
    planning = PlanningService(db, client)
    interview_service = InterviewService(db, client)

    study = planning.get_study(study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    rubric = planning.get_active_rubric(study_id)
    if not rubric:
        raise HTTPException(status_code=400, detail="No active rubric for study")

    config = InterviewConfig(
        participant_id=data.participant_id,
        participant_context=data.participant_context,
    )

    interview, opening = interview_service.start_interview(study, config)

    return ConversationResponse(
        interview_id=interview.id,
        status=interview.status.value,
        messages=[MessageResponse(role="interviewer", content=opening)],
    )


@app.get("/api/interviews/{interview_id}", response_model=ConversationResponse)
def get_interview(interview_id: int, db: Session = Depends(get_db)):
    """Get interview conversation."""
    client = get_anthropic_client()
    service = InterviewService(db, client)

    interview = service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    messages = []
    for msg in interview.messages:
        probe_data = None
        if msg.probe_decision:
            probe_data = {
                "action": msg.probe_decision.action.value,
                "reasoning": msg.probe_decision.reasoning,
                "signals": msg.probe_decision.signals,
            }
        messages.append(MessageResponse(
            role=msg.role.value,
            content=msg.content,
            probe_decision=probe_data,
        ))

    state = interview_service.get_interview_state(interview)

    return ConversationResponse(
        interview_id=interview.id,
        status=interview.status.value,
        messages=messages,
        state={
            "coverage": state.coverage,
            "average_depth": state.average_depth,
            "time_remaining": state.time_remaining,
            "message_count": state.message_count,
        } if state else None,
    )


@app.post("/api/interviews/{interview_id}/respond", response_model=InterviewerResponse)
def respond_to_interview(
    interview_id: int,
    data: ParticipantMessage,
    db: Session = Depends(get_db),
):
    """Send participant message and get interviewer response."""
    client = get_anthropic_client()
    service = InterviewService(db, client)

    interview = service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    if interview.status.value != "in_progress":
        raise HTTPException(status_code=400, detail="Interview is not in progress")

    response, decision = service.process_response(interview, data.message)

    # Refresh to check if completed
    db.refresh(interview)

    return InterviewerResponse(
        message=response,
        probe_decision={
            "action": decision.action.value,
            "reasoning": decision.reasoning,
            "confidence": decision.confidence,
            "signals": [
                {"type": s.signal_type.value, "confidence": s.confidence, "evidence": s.evidence}
                for s in decision.signals
            ],
        },
        is_complete=interview.status.value == "completed",
    )


@app.post("/api/interviews/{interview_id}/end")
def end_interview(interview_id: int, db: Session = Depends(get_db)):
    """End an interview."""
    client = get_anthropic_client()
    service = InterviewService(db, client)

    interview = service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    closing = service.end_interview(interview)

    return {"message": closing, "status": "completed"}


@app.get("/api/interviews/{interview_id}/transcript")
def get_transcript(interview_id: int, db: Session = Depends(get_db)):
    """Get interview transcript."""
    client = get_anthropic_client()
    service = InterviewService(db, client)

    interview = service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    return {"transcript": interview.transcript}


# =============================================================================
# Health Check
# =============================================================================


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {
        "status": "healthy",
        "api_key_configured": api_key_set,
    }
