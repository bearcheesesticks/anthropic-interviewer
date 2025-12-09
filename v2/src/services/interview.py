"""Interview Service - Conducts and manages adaptive interviews."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from anthropic import Anthropic
from sqlalchemy.orm import Session

from src.db.models import (
    Interview,
    Message,
    ProbeDecisionRecord,
    Rubric,
    Study,
    InterviewStatus,
    MessageRole,
    ProbeAction as DBProbeAction,
)
from src.core.models import (
    InterviewConfig,
    InterviewState,
    ProbeDecision,
    ConversationState,
    MessageRole as CoreMessageRole,
)
from src.core.probing import ProbingEngine
from src.services.planning import PlanningService


INTERVIEW_SYSTEM_PROMPT = """You are a skilled qualitative research interviewer. Your goal is to have a natural, flowing conversation while gathering rich data.

## Study Context
Research Goals: {research_goals}

## Your Interview Style
- Warm, curious, and non-judgmental
- Active listener who reflects back what participants say
- Comfortable with silence - give space for reflection
- Adaptive to participant's communication style

## Interviewer Guidance
{guidance}

## Interview Rubric
{rubric_summary}

## Critical Rules
1. NEVER lead the participant toward a particular answer
2. NEVER share your own opinions or experiences
3. NEVER rush - depth over breadth
4. If participant seems distressed, offer to pause or skip

Stay in character as the interviewer throughout."""


OPENING_PROMPT = """Begin the interview with a warm introduction.

Include:
1. Brief greeting and thanks for their time
2. Quick explanation of the study purpose (1 sentence)
3. Confirm consent and confidentiality
4. Set time expectations
5. First question from the rubric

Keep it conversational and natural, not scripted."""


class InterviewService:
    """Service for conducting adaptive interviews."""

    def __init__(
        self,
        db: Session,
        client: Optional[Anthropic] = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.db = db
        self.client = client or Anthropic()
        self.model = model
        self.probing_engine = ProbingEngine(client, model)
        self.planning_service = PlanningService(db, client, model)

        # In-memory state cache (keyed by interview_id)
        self._state_cache: dict[int, ConversationState] = {}

    # =========================================================================
    # Interview Lifecycle
    # =========================================================================

    def start_interview(
        self,
        study: Study,
        config: InterviewConfig,
    ) -> tuple[Interview, str]:
        """Start a new interview session.

        Returns:
            Tuple of (Interview, opening_message)
        """
        # Get active rubric
        rubric = self.planning_service.get_active_rubric(study.id)
        if not rubric:
            raise ValueError(f"No active rubric for study {study.id}")

        # Create interview record
        interview = Interview(
            study_id=study.id,
            rubric_id=rubric.id,
            participant_id=config.participant_id,
            participant_context=config.participant_context,
            status=InterviewStatus.IN_PROGRESS,
            show_probing_analysis=config.show_probing_analysis,
        )
        self.db.add(interview)
        self.db.commit()
        self.db.refresh(interview)

        # Initialize conversation state
        sections = self.planning_service.rubric_to_sections(rubric)
        state = self.probing_engine.initialize_state(
            sections,
            target_duration=study.target_duration_minutes,
        )
        self._state_cache[interview.id] = state

        # Store state in DB for persistence
        interview.conversation_state = state.model_dump()
        self.db.commit()

        # Generate opening message
        opening = self._generate_opening(interview, rubric, study)

        # Save opening message
        self._save_message(interview, CoreMessageRole.INTERVIEWER, opening, sequence=0)

        return interview, opening

    def process_response(
        self,
        interview: Interview,
        participant_message: str,
    ) -> tuple[str, ProbeDecision]:
        """Process participant response and generate interviewer reply.

        Returns:
            Tuple of (interviewer_response, probe_decision)
        """
        # Get or restore state
        state = self._get_state(interview)

        # Get research goal
        research_goal = "; ".join(interview.study.research_goals)

        # Save participant message
        sequence = len(interview.messages)
        self._save_message(interview, CoreMessageRole.PARTICIPANT, participant_message, sequence)

        # Check for end conditions
        if self._should_end(interview, participant_message, state):
            return self._end_interview(interview, state)

        # Detect signals in response
        signals = self.probing_engine.detect_signals(
            participant_message,
            state,
            research_goal,
        )

        # Decide probe action
        decision = self.probing_engine.decide_action(signals, state)

        # Build recent conversation context
        recent = self._get_recent_conversation(interview, n=4)

        # Generate response
        response = self._generate_response(
            interview,
            decision,
            state,
            recent,
            research_goal,
        )

        # Update state (pass interviewer response to track questions asked)
        state = self.probing_engine.update_state(
            state, participant_message, decision, interviewer_response=response
        )
        self._save_state(interview, state)

        # Save interviewer message with probe decision
        self._save_message(
            interview,
            CoreMessageRole.INTERVIEWER,
            response,
            sequence + 1,
            decision,
        )

        return response, decision

    def end_interview(self, interview: Interview) -> str:
        """Explicitly end an interview."""
        state = self._get_state(interview)
        return self._end_interview(interview, state)[0]

    def get_interview_state(self, interview: Interview) -> InterviewState:
        """Get current state of an interview."""
        state = self._get_state(interview)

        return InterviewState(
            id=interview.id,
            status=interview.status,
            participant_id=interview.participant_id,
            message_count=len(interview.messages),
            duration_minutes=interview.duration_minutes,
            coverage=state.coverage_ratio() if state.topics else None,
            average_depth=state.average_depth() if state.topics else None,
            time_remaining=state.time_remaining() if state else None,
            started_at=interview.started_at,
            ended_at=interview.ended_at,
        )

    # =========================================================================
    # Interview Queries
    # =========================================================================

    def get_interview(self, interview_id: int) -> Optional[Interview]:
        """Get interview by ID."""
        return self.db.query(Interview).filter(Interview.id == interview_id).first()

    def list_interviews(self, study_id: int) -> list[Interview]:
        """List all interviews for a study."""
        return self.db.query(Interview).filter(
            Interview.study_id == study_id
        ).order_by(Interview.started_at.desc()).all()

    def get_transcript(self, interview: Interview) -> str:
        """Get interview transcript."""
        return interview.transcript

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _generate_opening(
        self,
        interview: Interview,
        rubric: Rubric,
        study: Study,
    ) -> str:
        """Generate opening message for interview."""

        # Build rubric summary
        rubric_summary = self._build_rubric_summary(rubric)
        guidance = rubric.guidance or {}

        system_prompt = INTERVIEW_SYSTEM_PROMPT.format(
            research_goals="\n".join(f"- {g}" for g in study.research_goals),
            guidance=self._format_guidance(guidance),
            rubric_summary=rubric_summary,
        )

        # Include participant context if provided
        user_prompt = OPENING_PROMPT
        if interview.participant_context:
            user_prompt += f"\n\nParticipant context: {interview.participant_context}"

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return response.content[0].text

    def _generate_response(
        self,
        interview: Interview,
        decision: ProbeDecision,
        state: ConversationState,
        recent_conversation: str,
        research_goal: str,
    ) -> str:
        """Generate interviewer response using probing engine."""

        return self.probing_engine.generate_probe(
            decision,
            state,
            recent_conversation,
            research_goal,
        )

    def _should_end(
        self,
        interview: Interview,
        message: str,
        state: ConversationState,
    ) -> bool:
        """Determine if interview should end."""

        # Explicit end signals
        end_phrases = [
            "goodbye", "i need to go", "that's all", "wrap up",
            "no more questions", "i'm done"
        ]
        if any(phrase in message.lower() for phrase in end_phrases):
            return True

        # Time-based
        if state.time_remaining() <= 0 and state.coverage_ratio() > 0.5:
            return True

        # All topics covered deeply
        if state.coverage_ratio() >= 1.0 and state.average_depth() >= 2.5:
            return True

        # Message limit (safety)
        if len(interview.messages) >= 50:
            return True

        return False

    def _end_interview(
        self,
        interview: Interview,
        state: ConversationState,
    ) -> tuple[str, ProbeDecision]:
        """End the interview and return closing message."""

        closing = (
            "Thank you so much for taking the time to share your experiences with me today. "
            "Your insights are incredibly valuable for our research. "
            "Is there anything else you'd like to add that we haven't covered?"
        )

        # Update interview status
        interview.status = InterviewStatus.COMPLETED
        interview.ended_at = datetime.utcnow()
        self.db.commit()

        # Save closing message
        sequence = len(interview.messages)
        decision = ProbeDecision(
            action=CoreMessageRole.INTERVIEWER,  # This is wrong, should be ProbeAction
            reasoning="Interview complete",
            confidence=1.0,
            signals=[],
        )

        # Fix: Use correct action type
        from src.core.models import ProbeAction
        decision = ProbeDecision(
            action=ProbeAction.CLOSE,
            reasoning="Interview complete",
            confidence=1.0,
            signals=[],
        )

        self._save_message(interview, CoreMessageRole.INTERVIEWER, closing, sequence, decision)

        return closing, decision

    def _get_state(self, interview: Interview) -> ConversationState:
        """Get conversation state from cache or restore from DB."""
        if interview.id in self._state_cache:
            return self._state_cache[interview.id]

        # Restore from DB
        if interview.conversation_state:
            state = ConversationState(**interview.conversation_state)
        else:
            # Initialize fresh
            rubric = interview.rubric
            sections = self.planning_service.rubric_to_sections(rubric)
            state = self.probing_engine.initialize_state(
                sections,
                target_duration=interview.study.target_duration_minutes,
            )

        self._state_cache[interview.id] = state
        return state

    def _save_state(self, interview: Interview, state: ConversationState) -> None:
        """Save conversation state to cache and DB."""
        self._state_cache[interview.id] = state
        interview.conversation_state = state.model_dump()
        self.db.commit()

    def _save_message(
        self,
        interview: Interview,
        role: CoreMessageRole,
        content: str,
        sequence: int,
        decision: Optional[ProbeDecision] = None,
    ) -> Message:
        """Save a message to the database."""

        # Map core role to DB role
        db_role = MessageRole(role.value)

        message = Message(
            interview_id=interview.id,
            sequence=sequence,
            role=db_role,
            content=content,
        )
        self.db.add(message)
        self.db.flush()

        # Save probe decision if provided
        if decision and role == CoreMessageRole.INTERVIEWER:
            probe_record = ProbeDecisionRecord(
                message_id=message.id,
                action=DBProbeAction(decision.action.value),
                reasoning=decision.reasoning,
                confidence=decision.confidence,
                signals=[s.model_dump() for s in decision.signals],
            )

            # Add state snapshot
            state = self._state_cache.get(interview.id)
            if state:
                probe_record.coverage_at_decision = state.coverage_ratio()
                probe_record.depth_at_decision = state.average_depth()
                probe_record.time_remaining_at_decision = state.time_remaining()

            self.db.add(probe_record)

        self.db.commit()
        return message

    def _get_recent_conversation(self, interview: Interview, n: int = 4) -> str:
        """Get recent conversation for context."""
        recent = interview.messages[-n:] if interview.messages else []
        lines = []
        for msg in recent:
            role = "Interviewer" if msg.role == MessageRole.INTERVIEWER else "Participant"
            lines.append(f"{role}: {msg.content}")
        return "\n\n".join(lines)

    def _build_rubric_summary(self, rubric: Rubric) -> str:
        """Build a summary of the rubric for the system prompt."""
        lines = []
        for section in rubric.sections:
            lines.append(f"\n## {section.name}")
            if section.purpose:
                lines.append(f"Purpose: {section.purpose}")
            for q in section.questions:
                lines.append(f"- [{q.question_id}] {q.text}")
                if q.probes:
                    for probe in q.probes[:2]:
                        lines.append(f"  → {probe}")
        return "\n".join(lines)

    def _format_guidance(self, guidance: dict) -> str:
        """Format interviewer guidance for prompt."""
        lines = []
        if guidance.get("tone"):
            lines.append(f"Tone: {guidance['tone']}")
        if guidance.get("pacing"):
            lines.append(f"Pacing: {guidance['pacing']}")
        if guidance.get("sensitive_topics"):
            lines.append(f"Sensitive Topics: {', '.join(guidance['sensitive_topics'])}")
        if guidance.get("probing_strategy"):
            lines.append(f"Probing: {guidance['probing_strategy']}")
        return "\n".join(lines) if lines else "Be warm, curious, and professional."
