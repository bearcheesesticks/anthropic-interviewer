"""Interview Execution Agent - conducts conversational interviews."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from anthropic import Anthropic

from prompts.interview import build_interview_prompt
from agents.planning import InterviewRubric
from agents.probing import (
    ProbingEngine,
    AdaptiveInterviewController,
    ConversationState,
    ProbeDecision,
    ProbeAction,
)


@dataclass
class InterviewMessage:
    """A single message in the interview."""

    role: str  # "interviewer" or "participant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    probe_decision: ProbeDecision | None = None  # Attached for interviewer messages


@dataclass
class InterviewSession:
    """A complete interview session."""

    session_id: str
    rubric: InterviewRubric
    participant_id: str
    messages: list[InterviewMessage] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append(InterviewMessage(role=role, content=content))

    def get_transcript(self) -> str:
        """Generate a readable transcript."""
        lines = []
        for msg in self.messages:
            speaker = "Interviewer" if msg.role == "interviewer" else "Participant"
            lines.append(f"{speaker}: {msg.content}")
        return "\n\n".join(lines)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "rubric": self.rubric.to_json(),
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in self.messages
            ],
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InterviewSession":
        """Reconstruct from dictionary."""
        session = cls(
            session_id=data["session_id"],
            rubric=InterviewRubric.from_json(data["rubric"]),
            participant_id=data["participant_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            ended_at=datetime.fromisoformat(data["ended_at"])
            if data.get("ended_at")
            else None,
            metadata=data.get("metadata", {}),
        )
        for msg in data["messages"]:
            session.messages.append(
                InterviewMessage(
                    role=msg["role"],
                    content=msg["content"],
                    timestamp=datetime.fromisoformat(msg["timestamp"]),
                )
            )
        return session


class InterviewAgent:
    """Agent that conducts conversational interviews following a rubric."""

    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.client = client or Anthropic()
        self.model = model

    def start_session(
        self,
        rubric: InterviewRubric,
        participant_id: str,
        participant_context: str = "",
        session_id: Optional[str] = None,
    ) -> InterviewSession:
        """Start a new interview session."""
        import uuid

        session = InterviewSession(
            session_id=session_id or str(uuid.uuid4())[:8],
            rubric=rubric,
            participant_id=participant_id,
            metadata={"participant_context": participant_context},
        )

        # Generate opening message
        opening = self._generate_response(session, participant_context, is_opening=True)
        session.add_message("interviewer", opening)

        return session

    def respond(
        self, session: InterviewSession, participant_message: str
    ) -> str:
        """Process participant response and generate next interviewer message."""

        session.add_message("participant", participant_message)

        # Check if interview should end
        if self._should_end_interview(session, participant_message):
            closing = self._generate_closing(session)
            session.add_message("interviewer", closing)
            session.ended_at = datetime.now()
            return closing

        response = self._generate_response(session)
        session.add_message("interviewer", response)

        return response

    def _build_messages(
        self, session: InterviewSession, is_opening: bool = False
    ) -> list[dict]:
        """Build message history for the API call."""

        messages = []

        if is_opening:
            # For opening, just request to start
            messages.append(
                {
                    "role": "user",
                    "content": "Please begin the interview with your introduction.",
                }
            )
        else:
            # Build conversation history
            # Start with implicit opening prompt
            messages.append(
                {
                    "role": "user",
                    "content": "Please begin the interview with your introduction.",
                }
            )

            for msg in session.messages:
                role = "assistant" if msg.role == "interviewer" else "user"
                messages.append({"role": role, "content": msg.content})

        return messages

    def _generate_response(
        self,
        session: InterviewSession,
        participant_context: str = "",
        is_opening: bool = False,
    ) -> str:
        """Generate the next interviewer response."""

        system_prompt = build_interview_prompt(
            session.rubric.to_json(),
            participant_context or session.metadata.get("participant_context", ""),
        )

        messages = self._build_messages(session, is_opening)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )

        return response.content[0].text

    def _should_end_interview(
        self, session: InterviewSession, last_message: str
    ) -> bool:
        """Determine if the interview should conclude."""

        # Check for explicit end signals
        end_signals = [
            "goodbye",
            "thank you for your time",
            "that's all",
            "no more questions",
            "i need to go",
            "wrap up",
        ]

        if any(signal in last_message.lower() for signal in end_signals):
            return True

        # Check if we've covered enough ground (heuristic: message count)
        # A 10-15 minute interview typically has 15-25 exchanges
        if len(session.messages) >= 30:
            return True

        return False

    def _generate_closing(self, session: InterviewSession) -> str:
        """Generate a closing message for the interview."""

        return self._generate_response(session)

    def end_session(self, session: InterviewSession) -> InterviewSession:
        """Explicitly end an interview session."""
        if not session.ended_at:
            closing = "Thank you so much for taking the time to share your experiences with me today. Your insights are truly valuable for our research. If you have any questions about the study or would like to follow up, please don't hesitate to reach out. Take care!"
            session.add_message("interviewer", closing)
            session.ended_at = datetime.now()
        return session


class AdaptiveInterviewAgent:
    """
    Enhanced interview agent with intelligent probing.

    Uses the ProbingEngine to make smart decisions about when to:
    - Probe deeper into interesting responses
    - Ask for clarification on vague answers
    - Move on when topics are exhausted
    - Circle back to earlier points
    - Redirect away from discomfort
    """

    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.client = client or Anthropic()
        self.model = model
        self.probing_engine = ProbingEngine(client, model)
        self.controller: AdaptiveInterviewController | None = None
        self._conversation_state: ConversationState | None = None

    def start_session(
        self,
        rubric: InterviewRubric,
        participant_id: str,
        research_goal: str = "",
        participant_context: str = "",
        session_id: Optional[str] = None,
        target_duration: int = 15,
    ) -> InterviewSession:
        """Start a new adaptive interview session."""
        import uuid

        session = InterviewSession(
            session_id=session_id or str(uuid.uuid4())[:8],
            rubric=rubric,
            participant_id=participant_id,
            metadata={
                "participant_context": participant_context,
                "research_goal": research_goal,
                "adaptive_mode": True,
            },
        )

        # Initialize the probing controller
        self.controller = AdaptiveInterviewController(self.client, self.model)
        self.controller.initialize(
            rubric=rubric.to_json(),
            research_goal=research_goal or self._infer_research_goal(rubric),
            target_duration=target_duration,
        )
        self._conversation_state = self.controller.state

        # Generate opening message (standard, not probing-based)
        opening = self._generate_opening(session, participant_context)
        session.add_message("interviewer", opening)

        # Store in controller history
        self.controller.conversation_history.append({
            "role": "interviewer",
            "content": opening,
        })

        return session

    def respond(
        self,
        session: InterviewSession,
        participant_message: str,
    ) -> tuple[str, ProbeDecision]:
        """
        Process participant response and generate adaptive interviewer response.

        Returns:
            Tuple of (response_text, probe_decision)
        """
        if not self.controller:
            raise ValueError("Session not started. Call start_session() first.")

        session.add_message("participant", participant_message)

        # Check if interview should end
        if self._should_end_interview(session, participant_message):
            closing = self._generate_closing(session)
            session.add_message("interviewer", closing)
            session.ended_at = datetime.now()
            # Return a CLOSE decision
            close_decision = ProbeDecision(
                action=ProbeAction.CLOSE,
                reasoning="Interview ending (time or participant signal)",
                signals_detected=[],
                suggested_probe=closing,
                target_topic_id=None,
                confidence=1.0,
            )
            return closing, close_decision

        # Use probing engine to decide and generate response
        decision = self.controller.process_response(participant_message)

        # Use the probe decision to generate a contextually appropriate response
        response = self._generate_adaptive_response(session, decision)

        # Create message with attached decision
        msg = InterviewMessage(
            role="interviewer",
            content=response,
            probe_decision=decision,
        )
        session.messages.append(msg)

        return response, decision

    def get_interview_state(self) -> dict:
        """Get current state of the interview for monitoring."""
        if not self.controller:
            return {}
        return self.controller.get_state_summary()

    def _generate_opening(
        self,
        session: InterviewSession,
        participant_context: str,
    ) -> str:
        """Generate the opening message for the interview."""
        system_prompt = build_interview_prompt(
            session.rubric.to_json(),
            participant_context,
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": "Please begin the interview with your introduction.",
                }
            ],
        )

        return response.content[0].text

    def _generate_adaptive_response(
        self,
        session: InterviewSession,
        decision: ProbeDecision,
    ) -> str:
        """Generate response informed by the probe decision."""

        # Build the context for response generation
        participant_context = session.metadata.get("participant_context", "")

        # Create an augmented system prompt that includes the probe guidance
        base_prompt = build_interview_prompt(
            session.rubric.to_json(),
            participant_context,
        )

        probe_guidance = f"""
## Probe Guidance for This Response

**Action**: {decision.action.value}
**Reasoning**: {decision.reasoning}
**Suggested Probe**: {decision.suggested_probe}

Follow this guidance while maintaining natural conversation flow.
If the suggested probe fits naturally, use it. Otherwise, adapt it
to match the conversation while achieving the same goal.

Signals detected in the participant's last response:
{self._format_signals(decision.signals_detected)}
"""

        augmented_prompt = base_prompt + probe_guidance

        # Build conversation history
        messages = [
            {
                "role": "user",
                "content": "Please begin the interview with your introduction.",
            }
        ]

        for msg in session.messages:
            role = "assistant" if msg.role == "interviewer" else "user"
            messages.append({"role": role, "content": msg.content})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=augmented_prompt,
            messages=messages,
        )

        return response.content[0].text

    def _format_signals(self, signals: list) -> str:
        """Format detected signals for the prompt."""
        if not signals:
            return "- No strong signals detected"

        lines = []
        for s in signals[:5]:
            lines.append(
                f"- {s.signal_type.value.upper()}: {s.evidence} "
                f"(confidence: {s.confidence:.1f})"
            )
        return "\n".join(lines)

    def _should_end_interview(
        self,
        session: InterviewSession,
        last_message: str,
    ) -> bool:
        """Determine if the interview should conclude."""
        # Check for explicit end signals
        end_signals = [
            "goodbye",
            "thank you for your time",
            "that's all",
            "no more questions",
            "i need to go",
            "wrap up",
        ]

        if any(signal in last_message.lower() for signal in end_signals):
            return True

        # Use conversation state for smarter end detection
        if self._conversation_state:
            time_remaining = self._conversation_state.time_remaining_minutes()
            coverage = self._conversation_state.coverage_ratio()

            # End if time is up and we have decent coverage
            if time_remaining <= 0 and coverage > 0.5:
                return True

            # End if all topics covered deeply
            if coverage >= 1.0 and self._conversation_state.average_depth() >= 2:
                return True

        # Fallback: message count limit
        if len(session.messages) >= 40:
            return True

        return False

    def _generate_closing(self, session: InterviewSession) -> str:
        """Generate a closing message."""
        return (
            "Thank you so much for taking the time to share your experiences "
            "with me today. Your insights are truly valuable for our research. "
            "Is there anything else you'd like to add that we haven't covered?"
        )

    def _infer_research_goal(self, rubric: InterviewRubric) -> str:
        """Infer research goal from rubric if not provided."""
        goals = rubric.research_goals
        if goals:
            return "; ".join(goals)
        return "Understand participant experiences and perspectives"

    def end_session(self, session: InterviewSession) -> InterviewSession:
        """Explicitly end an interview session."""
        if not session.ended_at:
            final_closing = (
                "Thank you again for your time and thoughtful responses. "
                "Your participation helps us understand these issues better. "
                "Take care!"
            )
            session.add_message("interviewer", final_closing)
            session.ended_at = datetime.now()
        return session
