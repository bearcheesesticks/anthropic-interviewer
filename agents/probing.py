"""
Probing Decision Engine - determines when and how to probe deeper in interviews.

This module implements the core logic for adaptive interviewing:
- Detecting signals in participant responses that warrant different actions
- Tracking conversation state (coverage, depth, time)
- Selecting appropriate probe strategies
- Generating natural probe questions
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from anthropic import Anthropic


class ProbeAction(Enum):
    """What the interviewer should do next."""

    PROBE_DEEPER = "probe_deeper"  # Dig into current topic
    FOLLOW_UP = "follow_up"  # Ask related follow-up
    CIRCLE_BACK = "circle_back"  # Return to earlier topic
    MOVE_ON = "move_on"  # Advance to next rubric question
    CLARIFY = "clarify"  # Ask for clarification
    REFLECT = "reflect"  # Mirror back and validate
    REDIRECT = "redirect"  # Shift away (discomfort detected)
    CLOSE = "close"  # Begin closing the interview


class SignalType(Enum):
    """Signals detected in participant responses."""

    NOVELTY = "novelty"  # Unexpected/interesting content
    VAGUENESS = "vagueness"  # Abstract, needs concrete example
    EMOTION = "emotion"  # Strong feeling expressed
    CONTRADICTION = "contradiction"  # Conflicts with earlier statement
    REPETITION = "repetition"  # Rehashing same points
    BREVITY = "brevity"  # Very short response
    DISCOMFORT = "discomfort"  # Signs of unease
    ENTHUSIASM = "enthusiasm"  # High engagement, rich detail
    TANGENT = "tangent"  # Off-topic but potentially valuable
    COMPLETION = "completion"  # Topic fully explored


@dataclass
class DetectedSignal:
    """A signal detected in a participant response."""

    signal_type: SignalType
    confidence: float  # 0-1
    evidence: str  # Quote or description
    suggested_action: ProbeAction


@dataclass
class TopicState:
    """Tracking state for a single topic/question."""

    question_id: str
    question_text: str
    times_addressed: int = 0
    depth_achieved: int = 0  # 0=not asked, 1=surface, 2=explored, 3=deep
    key_points: list[str] = field(default_factory=list)
    needs_revisit: bool = False
    revisit_reason: str = ""


@dataclass
class ConversationState:
    """Full state of the interview conversation."""

    topics: dict[str, TopicState] = field(default_factory=dict)
    current_topic_id: Optional[str] = None
    messages_count: int = 0
    estimated_minutes_elapsed: float = 0.0
    target_duration_minutes: int = 15
    themes_emerged: list[str] = field(default_factory=list)
    items_to_circle_back: list[dict] = field(default_factory=list)
    participant_style: str = "unknown"  # verbose, concise, tangential, etc.

    def time_remaining_minutes(self) -> float:
        return max(0, self.target_duration_minutes - self.estimated_minutes_elapsed)

    def coverage_ratio(self) -> float:
        """What fraction of topics have been addressed at least once."""
        if not self.topics:
            return 0.0
        addressed = sum(1 for t in self.topics.values() if t.times_addressed > 0)
        return addressed / len(self.topics)

    def average_depth(self) -> float:
        """Average depth achieved across addressed topics."""
        addressed = [t for t in self.topics.values() if t.times_addressed > 0]
        if not addressed:
            return 0.0
        return sum(t.depth_achieved for t in addressed) / len(addressed)

    def get_unaddressed_topics(self) -> list[TopicState]:
        """Topics not yet covered."""
        return [t for t in self.topics.values() if t.times_addressed == 0]

    def get_shallow_topics(self) -> list[TopicState]:
        """Topics addressed but not deeply explored."""
        return [
            t for t in self.topics.values()
            if t.times_addressed > 0 and t.depth_achieved < 2
        ]


@dataclass
class ProbeDecision:
    """The output of the probing decision engine."""

    action: ProbeAction
    reasoning: str
    signals_detected: list[DetectedSignal]
    suggested_probe: str  # The actual question/statement to use
    target_topic_id: Optional[str]  # Which topic this addresses
    confidence: float  # How confident in this decision


SIGNAL_DETECTION_PROMPT = """Analyze this interview exchange and detect signals that should influence the interviewer's next move.

## Interview Context
Research Goal: {research_goal}
Current Topic: {current_topic}
Time Remaining: ~{time_remaining} minutes
Topics Not Yet Covered: {uncovered_count}

## Recent Exchange
{recent_exchange}

## Signal Types to Detect

1. **NOVELTY**: Participant mentioned something unexpected, interesting, or unique
   - Look for: surprising experiences, unconventional views, specific details

2. **VAGUENESS**: Response is abstract or general, needs concrete grounding
   - Look for: generalizations, "usually", "sometimes", lack of specific examples

3. **EMOTION**: Strong feeling expressed (positive or negative)
   - Look for: emphatic language, personal stakes, frustration, excitement

4. **CONTRADICTION**: Conflicts with something said earlier
   - Look for: inconsistencies with earlier statements (provided below if relevant)

5. **REPETITION**: Participant is rehashing the same points
   - Look for: circular logic, restating previous answers

6. **BREVITY**: Unusually short response that might indicate disengagement or discomfort
   - Look for: one-word answers, minimal elaboration when more was expected

7. **DISCOMFORT**: Signs the participant is uneasy with the topic
   - Look for: hedging, deflection, nervous qualifiers, wanting to move on

8. **ENTHUSIASM**: High engagement, rich unprompted detail
   - Look for: long responses, specific examples offered freely, animated language

9. **TANGENT**: Off-topic but potentially valuable digression
   - Look for: related but unexpected directions, personal stories

10. **COMPLETION**: Topic seems fully explored, natural ending point
    - Look for: summary statements, "that's basically it", repetition of main point

## Earlier Relevant Statements (for contradiction detection)
{earlier_statements}

## Output Format
Return JSON:
```json
{{
  "signals": [
    {{
      "signal_type": "SIGNAL_NAME",
      "confidence": 0.0-1.0,
      "evidence": "exact quote or description",
      "suggested_action": "probe_deeper|follow_up|circle_back|move_on|clarify|reflect|redirect|close"
    }}
  ],
  "participant_style_notes": "observations about how this participant communicates",
  "primary_signal": "the most important signal to respond to"
}}
```

Detect ALL relevant signals, even subtle ones. Be specific in your evidence."""


PROBE_GENERATION_PROMPT = """Generate the interviewer's next response based on the probe decision.

## Context
Research Goal: {research_goal}
Current Topic: {current_topic}
Decided Action: {action}
Reasoning: {reasoning}

## Signals Detected
{signals_summary}

## Conversation So Far (last 3 exchanges)
{recent_conversation}

## Probe Guidelines by Action Type

**PROBE_DEEPER**: Dig into specifics of what they just said
- "Can you walk me through a specific time when that happened?"
- "What did that actually look like day-to-day?"
- "You mentioned [X] — tell me more about that."

**FOLLOW_UP**: Explore a related angle
- "How does that connect to [related topic]?"
- "And what about when [related scenario]?"

**CLARIFY**: Resolve vagueness or confusion
- "When you say [term], what do you mean by that?"
- "Help me understand — are you saying [interpretation A] or [interpretation B]?"

**REFLECT**: Mirror back and validate before continuing
- "So it sounds like [summary]. Is that right?"
- "That's really interesting — [brief validation]. [Follow-up]"

**CIRCLE_BACK**: Return to earlier topic
- "Earlier you mentioned [X]. I'd love to hear more about that."
- "Going back to something you said before about [X]..."

**REDIRECT**: Gently shift away from discomfort
- "That makes sense. Let me ask about something a bit different..."
- "I appreciate you sharing that. Shifting gears a bit..."

**MOVE_ON**: Transition to next topic naturally
- "That's really helpful context. I'm curious about [next topic]..."
- "Building on that — [next question]"

**CLOSE**: Begin wrapping up
- "We're coming up on time. Before we wrap, is there anything else..."

## Style Requirements
- Sound natural and conversational, not robotic
- Don't stack multiple questions
- Acknowledge what they said before asking more
- Match their energy level appropriately
- Keep it concise — this is a prompt, not a speech

## Output Format
Return JSON:
```json
{{
  "probe_text": "The exact words the interviewer should say",
  "backup_probe": "Alternative if the main probe doesn't fit",
  "transition_needed": true/false,
  "acknowledgment": "Brief acknowledgment of their response (optional)"
}}
```"""


class ProbingEngine:
    """
    Engine that decides when and how to probe during interviews.

    This is the core adaptive logic that makes interviews feel natural
    while ensuring research goals are met.
    """

    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.client = client or Anthropic()
        self.model = model

    def initialize_state(
        self,
        rubric: dict,
        target_duration: int = 15,
    ) -> ConversationState:
        """Initialize conversation state from a rubric."""
        state = ConversationState(target_duration_minutes=target_duration)

        # Extract all questions from rubric
        for section in rubric.get("sections", []):
            for question in section.get("questions", []):
                q_id = question.get("id", f"q_{len(state.topics)}")
                state.topics[q_id] = TopicState(
                    question_id=q_id,
                    question_text=question.get("text", ""),
                )

        return state

    def update_state(
        self,
        state: ConversationState,
        participant_message: str,
        interviewer_message: str,
        topic_id: Optional[str] = None,
    ) -> ConversationState:
        """Update state after an exchange."""
        state.messages_count += 2

        # Estimate time (rough heuristic: ~30 seconds per exchange)
        state.estimated_minutes_elapsed = state.messages_count * 0.25

        # Update topic state if we know which topic was addressed
        if topic_id and topic_id in state.topics:
            topic = state.topics[topic_id]
            topic.times_addressed += 1

            # Estimate depth based on response length and probing
            words = len(participant_message.split())
            if words > 100:
                topic.depth_achieved = max(topic.depth_achieved, 3)
            elif words > 50:
                topic.depth_achieved = max(topic.depth_achieved, 2)
            else:
                topic.depth_achieved = max(topic.depth_achieved, 1)

            state.current_topic_id = topic_id

        return state

    def detect_signals(
        self,
        state: ConversationState,
        recent_exchange: str,
        research_goal: str,
        earlier_statements: Optional[list[str]] = None,
    ) -> list[DetectedSignal]:
        """Detect signals in the participant's response."""

        current_topic = ""
        if state.current_topic_id and state.current_topic_id in state.topics:
            current_topic = state.topics[state.current_topic_id].question_text

        prompt = SIGNAL_DETECTION_PROMPT.format(
            research_goal=research_goal,
            current_topic=current_topic or "General exploration",
            time_remaining=f"{state.time_remaining_minutes():.0f}",
            uncovered_count=len(state.get_unaddressed_topics()),
            recent_exchange=recent_exchange,
            earlier_statements="\n".join(earlier_statements) if earlier_statements else "None tracked",
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text
        data = self._extract_json(response_text)

        signals = []
        for sig in data.get("signals", []):
            try:
                signals.append(DetectedSignal(
                    signal_type=SignalType[sig["signal_type"].upper()],
                    confidence=float(sig.get("confidence", 0.5)),
                    evidence=sig.get("evidence", ""),
                    suggested_action=ProbeAction(sig.get("suggested_action", "follow_up")),
                ))
            except (KeyError, ValueError):
                continue

        # Update participant style if noted
        if data.get("participant_style_notes"):
            state.participant_style = data["participant_style_notes"]

        return signals

    def decide_probe(
        self,
        state: ConversationState,
        signals: list[DetectedSignal],
        research_goal: str,
    ) -> ProbeDecision:
        """Decide what probe action to take based on signals and state."""

        # Priority logic for action selection
        action, reasoning, target_topic = self._select_action(state, signals)

        # Generate the actual probe text
        probe_text = self._generate_probe(
            state=state,
            action=action,
            signals=signals,
            research_goal=research_goal,
            target_topic=target_topic,
        )

        return ProbeDecision(
            action=action,
            reasoning=reasoning,
            signals_detected=signals,
            suggested_probe=probe_text,
            target_topic_id=target_topic,
            confidence=self._calculate_confidence(signals, state),
        )

    def _select_action(
        self,
        state: ConversationState,
        signals: list[DetectedSignal],
    ) -> tuple[ProbeAction, str, Optional[str]]:
        """Select the best action based on signals and state."""

        # Check for discomfort first — always redirect if detected
        discomfort = [s for s in signals if s.signal_type == SignalType.DISCOMFORT]
        if discomfort and discomfort[0].confidence > 0.6:
            return (
                ProbeAction.REDIRECT,
                f"Detected discomfort: {discomfort[0].evidence}",
                None,
            )

        # Check time pressure
        time_remaining = state.time_remaining_minutes()
        uncovered = state.get_unaddressed_topics()

        if time_remaining < 3 and len(uncovered) > 2:
            # Need to wrap up
            return (
                ProbeAction.CLOSE,
                f"Only {time_remaining:.0f} min left with {len(uncovered)} topics uncovered",
                None,
            )

        if time_remaining < 5 and len(uncovered) > 0:
            # Time pressure — prioritize coverage over depth
            next_topic = uncovered[0]
            return (
                ProbeAction.MOVE_ON,
                f"Time pressure: moving to uncovered topic '{next_topic.question_text[:50]}...'",
                next_topic.question_id,
            )

        # Check for high-value signals worth probing
        novelty = [s for s in signals if s.signal_type == SignalType.NOVELTY]
        if novelty and novelty[0].confidence > 0.7:
            return (
                ProbeAction.PROBE_DEEPER,
                f"Novel content detected: {novelty[0].evidence}",
                state.current_topic_id,
            )

        emotion = [s for s in signals if s.signal_type == SignalType.EMOTION]
        if emotion and emotion[0].confidence > 0.6:
            return (
                ProbeAction.PROBE_DEEPER,
                f"Strong emotion detected: {emotion[0].evidence}",
                state.current_topic_id,
            )

        # Check for signals that need clarification
        vagueness = [s for s in signals if s.signal_type == SignalType.VAGUENESS]
        if vagueness and vagueness[0].confidence > 0.7:
            return (
                ProbeAction.CLARIFY,
                f"Response too vague: {vagueness[0].evidence}",
                state.current_topic_id,
            )

        contradiction = [s for s in signals if s.signal_type == SignalType.CONTRADICTION]
        if contradiction and contradiction[0].confidence > 0.6:
            return (
                ProbeAction.CLARIFY,
                f"Contradiction with earlier statement: {contradiction[0].evidence}",
                state.current_topic_id,
            )

        # Check for completion signals
        completion = [s for s in signals if s.signal_type == SignalType.COMPLETION]
        repetition = [s for s in signals if s.signal_type == SignalType.REPETITION]

        if (completion and completion[0].confidence > 0.7) or (repetition and repetition[0].confidence > 0.7):
            # Topic exhausted — check if we should circle back or move on
            if state.items_to_circle_back:
                item = state.items_to_circle_back.pop(0)
                return (
                    ProbeAction.CIRCLE_BACK,
                    f"Topic complete, circling back to: {item.get('topic', 'earlier point')}",
                    item.get("topic_id"),
                )

            if uncovered:
                next_topic = uncovered[0]
                return (
                    ProbeAction.MOVE_ON,
                    f"Topic complete, advancing to: '{next_topic.question_text[:50]}...'",
                    next_topic.question_id,
                )

        # Check for tangent worth noting for later
        tangent = [s for s in signals if s.signal_type == SignalType.TANGENT]
        if tangent and tangent[0].confidence > 0.6:
            # Note for circle back but continue current thread
            state.items_to_circle_back.append({
                "topic": tangent[0].evidence,
                "topic_id": None,
            })

        # Check for enthusiasm — ride the wave
        enthusiasm = [s for s in signals if s.signal_type == SignalType.ENTHUSIASM]
        if enthusiasm and enthusiasm[0].confidence > 0.6:
            return (
                ProbeAction.FOLLOW_UP,
                f"High engagement detected, following their energy",
                state.current_topic_id,
            )

        # Default: reflect and follow up
        return (
            ProbeAction.REFLECT,
            "No strong signals — acknowledge and continue exploring",
            state.current_topic_id,
        )

    def _generate_probe(
        self,
        state: ConversationState,
        action: ProbeAction,
        signals: list[DetectedSignal],
        research_goal: str,
        target_topic: Optional[str],
    ) -> str:
        """Generate the actual probe text using LLM."""

        current_topic = ""
        if target_topic and target_topic in state.topics:
            current_topic = state.topics[target_topic].question_text
        elif state.current_topic_id and state.current_topic_id in state.topics:
            current_topic = state.topics[state.current_topic_id].question_text

        signals_summary = "\n".join(
            f"- {s.signal_type.value}: {s.evidence} (confidence: {s.confidence:.1f})"
            for s in signals[:5]  # Top 5 signals
        )

        prompt = PROBE_GENERATION_PROMPT.format(
            research_goal=research_goal,
            current_topic=current_topic or "General exploration",
            action=action.value,
            reasoning=f"Selected {action.value} based on detected signals",
            signals_summary=signals_summary or "No strong signals detected",
            recent_conversation="[Context provided to interviewer agent]",
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text

        try:
            data = self._extract_json(response_text)
            probe_text = data.get("probe_text", "")

            # Optionally prepend acknowledgment
            ack = data.get("acknowledgment", "")
            if ack and data.get("transition_needed"):
                probe_text = f"{ack} {probe_text}"

            return probe_text
        except (json.JSONDecodeError, KeyError):
            # Fallback — return raw text
            return response_text.strip()

    def _calculate_confidence(
        self,
        signals: list[DetectedSignal],
        state: ConversationState,
    ) -> float:
        """Calculate confidence in the probe decision."""
        if not signals:
            return 0.5

        # Higher confidence if strong signals detected
        max_signal_confidence = max(s.confidence for s in signals)

        # Lower confidence if time-pressured
        time_factor = min(1.0, state.time_remaining_minutes() / 5)

        return (max_signal_confidence + time_factor) / 2

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
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            json_str = text[json_start:json_end]

        return json.loads(json_str)


class AdaptiveInterviewController:
    """
    High-level controller that combines probing engine with interview flow.

    This is the main interface for adaptive interviewing.
    """

    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.client = client or Anthropic()
        self.model = model
        self.probing_engine = ProbingEngine(client, model)
        self.state: ConversationState | None = None
        self.research_goal: str = ""
        self.conversation_history: list[dict] = []

    def initialize(
        self,
        rubric: dict,
        research_goal: str,
        target_duration: int = 15,
    ) -> None:
        """Initialize the controller for a new interview."""
        self.state = self.probing_engine.initialize_state(rubric, target_duration)
        self.research_goal = research_goal
        self.conversation_history = []

    def process_response(
        self,
        participant_message: str,
    ) -> ProbeDecision:
        """Process a participant response and decide next probe."""
        if not self.state:
            raise ValueError("Controller not initialized. Call initialize() first.")

        # Store in history
        self.conversation_history.append({
            "role": "participant",
            "content": participant_message,
        })

        # Build recent exchange context
        recent = self._get_recent_exchange()

        # Get earlier statements for contradiction detection
        earlier = self._get_earlier_statements()

        # Detect signals
        signals = self.probing_engine.detect_signals(
            state=self.state,
            recent_exchange=recent,
            research_goal=self.research_goal,
            earlier_statements=earlier,
        )

        # Decide probe
        decision = self.probing_engine.decide_probe(
            state=self.state,
            signals=signals,
            research_goal=self.research_goal,
        )

        # Update state
        self.state = self.probing_engine.update_state(
            state=self.state,
            participant_message=participant_message,
            interviewer_message=decision.suggested_probe,
            topic_id=decision.target_topic_id,
        )

        # Store interviewer response
        self.conversation_history.append({
            "role": "interviewer",
            "content": decision.suggested_probe,
        })

        return decision

    def get_state_summary(self) -> dict:
        """Get a summary of current interview state."""
        if not self.state:
            return {}

        return {
            "messages": self.state.messages_count,
            "time_elapsed": f"{self.state.estimated_minutes_elapsed:.1f} min",
            "time_remaining": f"{self.state.time_remaining_minutes():.1f} min",
            "coverage": f"{self.state.coverage_ratio() * 100:.0f}%",
            "average_depth": f"{self.state.average_depth():.1f}/3",
            "uncovered_topics": len(self.state.get_unaddressed_topics()),
            "participant_style": self.state.participant_style,
            "items_to_revisit": len(self.state.items_to_circle_back),
        }

    def _get_recent_exchange(self, n: int = 4) -> str:
        """Get the most recent exchange for context."""
        recent = self.conversation_history[-n:]
        lines = []
        for msg in recent:
            role = "Interviewer" if msg["role"] == "interviewer" else "Participant"
            lines.append(f"{role}: {msg['content']}")
        return "\n\n".join(lines)

    def _get_earlier_statements(self, n: int = 5) -> list[str]:
        """Get earlier participant statements for contradiction detection."""
        participant_msgs = [
            m["content"]
            for m in self.conversation_history[:-2]  # Exclude most recent
            if m["role"] == "participant"
        ]
        return participant_msgs[-n:] if participant_msgs else []
