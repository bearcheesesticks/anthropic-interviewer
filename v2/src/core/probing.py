"""Probing Engine - The core intelligence for adaptive interviewing.

This module implements:
1. Signal detection - Analyzing participant responses for actionable signals
2. Probe decision - Rule-based logic for selecting the best probe action
3. State tracking - Maintaining conversation state across the interview

Architecture:
- LLM detects signals in responses (via prompts)
- Rules decide action based on signals + state (deterministic)
- This hybrid approach balances adaptability with consistency
"""

from __future__ import annotations

import json
from typing import Optional

from anthropic import Anthropic

from src.core.models import (
    Signal,
    SignalType,
    ProbeAction,
    ProbeDecision,
    ConversationState,
    TopicState,
    SectionConfig,
)


# =============================================================================
# Prompts
# =============================================================================


SIGNAL_DETECTION_PROMPT = """Analyze this interview response and detect signals that should influence the interviewer's next move.

## Interview Context
Research Goal: {research_goal}
Current Topic: {current_topic}
Time Remaining: ~{time_remaining:.0f} minutes
Topics Not Yet Covered: {uncovered_count}

## Participant's Response
{response}

## Previous Context (for contradiction detection)
{previous_context}

## Signals to Detect

Analyze for each signal type. Only include signals you detect with reasonable confidence.

| Signal | What to Look For |
|--------|------------------|
| NOVELTY | Unexpected content, unique experiences, surprising perspectives |
| VAGUENESS | Generalizations ("usually", "sometimes"), lack of specific examples |
| EMOTION | Strong feelings, emphatic language, personal stakes, frustration/excitement |
| CONTRADICTION | Inconsistency with earlier statements (see previous context) |
| REPETITION | Restating previous points, circular reasoning |
| BREVITY | Unusually short response given the question asked |
| DISCOMFORT | Hedging, deflection, topic avoidance, nervous qualifiers |
| ENTHUSIASM | Long detailed response, unsolicited elaboration, animated language |
| TANGENT | Related but off-topic content that might be valuable |
| COMPLETION | Summary statements, "that's basically it", natural topic closure |

## Output Format
Return a JSON object:
```json
{{
    "signals": [
        {{
            "signal_type": "SIGNAL_NAME",
            "confidence": 0.0-1.0,
            "evidence": "exact quote or brief description"
        }}
    ],
    "primary_signal": "most important signal to respond to",
    "participant_style": "brief observation about communication style"
}}
```

Only include signals with confidence >= 0.4. Order by importance."""


PROBE_GENERATION_PROMPT = """Generate a natural interviewer response based on the probe decision.

## Context
Research Goal: {research_goal}
Current Topic: {current_topic}
Target Action: {action}
Reasoning: {reasoning}

## Signals Detected
{signals_summary}

## Conversation (last 2 exchanges)
{recent_conversation}

## Questions Already Asked
{questions_asked}

## Guidelines for {action}

{action_guidelines}

## Requirements
- Sound natural and conversational
- Acknowledge what they said before asking more
- Don't stack multiple questions
- Keep it concise (2-4 sentences max)
- Match their energy level appropriately
- IMPORTANT: Do NOT repeat or closely rephrase questions already asked above

Return only the interviewer's response text, nothing else."""


ACTION_GUIDELINES = {
    ProbeAction.PROBE_DEEPER: """
Dig into specifics of what they just said:
- "Can you walk me through a specific time when that happened?"
- "What did that actually look like in practice?"
- "You mentioned [X] — tell me more about that."
""",
    ProbeAction.FOLLOW_UP: """
Explore a related angle they opened up:
- "How does that connect to [related aspect]?"
- "And what about when [related scenario]?"
- "That's interesting — does that also affect [related area]?"
""",
    ProbeAction.CLARIFY: """
Resolve vagueness or apparent contradiction:
- "When you say [term], what do you mean exactly?"
- "Help me understand — earlier you mentioned [X], and now [Y]. How do those fit together?"
- "Can you give me a specific example of that?"
""",
    ProbeAction.REFLECT: """
Mirror back and validate before continuing:
- "So it sounds like [summary]. Is that right?"
- "That's really interesting — [brief validation]. [Gentle follow-up]"
- "I hear you saying [interpretation]. Did I get that right?"
""",
    ProbeAction.MOVE_ON: """
Transition to a new topic naturally:
- "That's really helpful context. I'm curious about [new topic]..."
- "Thanks for sharing that. Shifting gears a bit — [new question]"
- "That makes sense. Let me ask about something different..."
""",
    ProbeAction.CIRCLE_BACK: """
Return to an earlier point worth exploring:
- "Earlier you mentioned [X]. I'd love to hear more about that."
- "Going back to something you said before about [X]..."
- "You touched on [X] earlier — can we explore that more?"
""",
    ProbeAction.REDIRECT: """
Gently shift away from discomfort:
- "I appreciate you sharing that. Let me ask about something a bit different..."
- "That makes sense. Moving on — [new topic]"
- "Thanks for that perspective. I'm also curious about..."
""",
    ProbeAction.CLOSE: """
Begin wrapping up the interview:
- "We're coming up on time. Before we finish, is there anything else you'd like to share?"
- "This has been really valuable. Any final thoughts on [main topic]?"
- "One last question before we wrap up..."
""",
}


# =============================================================================
# Probing Engine
# =============================================================================


class ProbingEngine:
    """Engine that detects signals and decides probe actions.

    This is the core adaptive intelligence for interviews.

    Usage:
        engine = ProbingEngine(client)
        state = engine.initialize_state(rubric_sections, target_duration=15)

        # For each participant response:
        signals = engine.detect_signals(response, state, research_goal)
        decision = engine.decide_action(signals, state)
        probe_text = engine.generate_probe(decision, state, recent_conversation)

        # Update state
        state = engine.update_state(state, response, decision)
    """

    def __init__(
        self,
        client: Optional[Anthropic] = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.client = client or Anthropic()
        self.model = model

    def initialize_state(
        self,
        sections: list[SectionConfig],
        target_duration: int = 15,
    ) -> ConversationState:
        """Initialize conversation state from rubric sections."""
        state = ConversationState(target_duration_minutes=target_duration)

        for section in sections:
            for question in section.questions:
                state.topics[question.question_id] = TopicState(
                    question_id=question.question_id,
                    question_text=question.text,
                )

        return state

    def detect_signals(
        self,
        response: str,
        state: ConversationState,
        research_goal: str,
    ) -> list[Signal]:
        """Detect signals in a participant response using LLM."""

        # Build context
        current_topic = ""
        if state.current_topic_id and state.current_topic_id in state.topics:
            current_topic = state.topics[state.current_topic_id].question_text

        uncovered = [t for t in state.topics.values() if t.times_addressed == 0]

        # Previous statements for contradiction detection
        previous_context = "\n".join(
            f"- {stmt}" for stmt in state.earlier_statements[-5:]
        ) if state.earlier_statements else "No previous statements recorded."

        prompt = SIGNAL_DETECTION_PROMPT.format(
            research_goal=research_goal,
            current_topic=current_topic or "General exploration",
            time_remaining=state.time_remaining(),
            uncovered_count=len(uncovered),
            response=response,
            previous_context=previous_context,
        )

        llm_response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        response_text = llm_response.content[0].text
        data = self._extract_json(response_text)

        signals = []
        for sig in data.get("signals", []):
            try:
                signal_type = SignalType(sig["signal_type"].lower())
                signals.append(Signal(
                    signal_type=signal_type,
                    confidence=float(sig.get("confidence", 0.5)),
                    evidence=sig.get("evidence", ""),
                ))
            except (KeyError, ValueError):
                continue

        # Update participant style if noted
        if data.get("participant_style"):
            state.participant_style = data["participant_style"]

        return signals

    def decide_action(
        self,
        signals: list[Signal],
        state: ConversationState,
    ) -> ProbeDecision:
        """Decide probe action based on signals and state.

        This is rule-based for consistency across interviews.
        """
        action, reasoning, target = self._apply_decision_rules(signals, state)

        return ProbeDecision(
            action=action,
            reasoning=reasoning,
            confidence=self._calculate_confidence(signals, state),
            signals=signals,
            target_question_id=target,
        )

    def _apply_decision_rules(
        self,
        signals: list[Signal],
        state: ConversationState,
    ) -> tuple[ProbeAction, str, Optional[str]]:
        """Apply decision rules in priority order.

        Priority:
        1. Safety (discomfort) - always redirect
        2. Time pressure - ensure coverage
        3. High-value signals - probe deeper
        4. Clarification needs
        5. Topic exhaustion - move on
        6. Engagement - follow energy
        7. Default - reflect and continue
        """

        # Helper to find signal by type
        def find_signal(sig_type: SignalType, min_confidence: float = 0.5) -> Optional[Signal]:
            for s in signals:
                if s.signal_type == sig_type and s.confidence >= min_confidence:
                    return s
            return None

        uncovered = [t for t in state.topics.values() if t.times_addressed == 0]
        shallow = [t for t in state.topics.values() if t.times_addressed > 0 and t.depth_achieved < 2]
        time_remaining = state.time_remaining()

        # 1. DISCOMFORT - Always redirect (participant wellbeing first)
        discomfort = find_signal(SignalType.DISCOMFORT, 0.6)
        if discomfort:
            return (
                ProbeAction.REDIRECT,
                f"Discomfort detected: {discomfort.evidence}",
                None,
            )

        # 2. TIME PRESSURE - Ensure coverage
        if time_remaining < 2:
            return (
                ProbeAction.CLOSE,
                f"Only {time_remaining:.0f} min left, beginning to close",
                None,
            )

        if time_remaining < 5 and len(uncovered) > 2:
            next_topic = uncovered[0]
            return (
                ProbeAction.MOVE_ON,
                f"Time pressure: {len(uncovered)} topics uncovered with {time_remaining:.0f} min left",
                next_topic.question_id,
            )

        # 3. HIGH-VALUE SIGNALS - Worth probing deeper
        novelty = find_signal(SignalType.NOVELTY, 0.7)
        if novelty:
            return (
                ProbeAction.PROBE_DEEPER,
                f"Novel content worth exploring: {novelty.evidence}",
                state.current_topic_id,
            )

        emotion = find_signal(SignalType.EMOTION, 0.6)
        if emotion:
            return (
                ProbeAction.PROBE_DEEPER,
                f"Emotional content to explore: {emotion.evidence}",
                state.current_topic_id,
            )

        # 4. CLARIFICATION NEEDS
        vagueness = find_signal(SignalType.VAGUENESS, 0.7)
        if vagueness:
            return (
                ProbeAction.CLARIFY,
                f"Response needs grounding: {vagueness.evidence}",
                state.current_topic_id,
            )

        contradiction = find_signal(SignalType.CONTRADICTION, 0.6)
        if contradiction:
            return (
                ProbeAction.CLARIFY,
                f"Apparent contradiction to resolve: {contradiction.evidence}",
                state.current_topic_id,
            )

        # 5. TOPIC EXHAUSTION - Move on or circle back
        completion = find_signal(SignalType.COMPLETION, 0.7)
        repetition = find_signal(SignalType.REPETITION, 0.7)

        if completion or repetition:
            # Check if we have items to circle back to
            if state.items_to_circle_back:
                item = state.items_to_circle_back[0]  # Don't pop yet, do that in update_state
                return (
                    ProbeAction.CIRCLE_BACK,
                    f"Topic complete, circling back to: {item.get('topic', 'earlier point')}",
                    item.get("question_id"),
                )

            # Move to next uncovered topic
            if uncovered:
                next_topic = uncovered[0]
                return (
                    ProbeAction.MOVE_ON,
                    f"Topic explored, advancing to: {next_topic.question_text[:50]}...",
                    next_topic.question_id,
                )

            # All covered but shallow? Go deeper on something
            if shallow:
                topic = shallow[0]
                return (
                    ProbeAction.PROBE_DEEPER,
                    f"All topics covered, deepening: {topic.question_text[:50]}...",
                    topic.question_id,
                )

        # 6. ENGAGEMENT - Follow their energy
        enthusiasm = find_signal(SignalType.ENTHUSIASM, 0.6)
        if enthusiasm:
            return (
                ProbeAction.FOLLOW_UP,
                f"High engagement, following their energy",
                state.current_topic_id,
            )

        # Check for tangent worth noting
        tangent = find_signal(SignalType.TANGENT, 0.6)
        if tangent:
            # Note for later but don't derail current topic
            state.items_to_circle_back.append({
                "topic": tangent.evidence,
                "question_id": None,
            })

        # 7. BREVITY - Gentle probe for more
        brevity = find_signal(SignalType.BREVITY, 0.6)
        if brevity:
            return (
                ProbeAction.FOLLOW_UP,
                "Brief response, gently probing for more",
                state.current_topic_id,
            )

        # 8. DEFAULT - Reflect and continue
        return (
            ProbeAction.REFLECT,
            "No strong signals, acknowledging and continuing",
            state.current_topic_id,
        )

    def generate_probe(
        self,
        decision: ProbeDecision,
        state: ConversationState,
        recent_conversation: str,
        research_goal: str,
    ) -> str:
        """Generate natural probe text using LLM."""

        current_topic = ""
        if decision.target_question_id and decision.target_question_id in state.topics:
            current_topic = state.topics[decision.target_question_id].question_text
        elif state.current_topic_id and state.current_topic_id in state.topics:
            current_topic = state.topics[state.current_topic_id].question_text

        signals_summary = "\n".join(
            f"- {s.signal_type.value.upper()}: {s.evidence}"
            for s in decision.signals[:3]
        ) if decision.signals else "No strong signals detected"

        # Compact summary of questions already asked (to avoid repetition)
        questions_asked = "\n".join(
            f"- {q}" for q in state.recent_questions_asked[-6:]
        ) if state.recent_questions_asked else "None yet (opening of interview)"

        prompt = PROBE_GENERATION_PROMPT.format(
            research_goal=research_goal,
            current_topic=current_topic or "General discussion",
            action=decision.action.value.upper(),
            reasoning=decision.reasoning,
            signals_summary=signals_summary,
            recent_conversation=recent_conversation,
            questions_asked=questions_asked,
            action_guidelines=ACTION_GUIDELINES.get(decision.action, ""),
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text.strip()

    def update_state(
        self,
        state: ConversationState,
        participant_response: str,
        decision: ProbeDecision,
        interviewer_response: Optional[str] = None,
    ) -> ConversationState:
        """Update conversation state after an exchange."""

        state.messages_count += 2  # participant + interviewer

        # Estimate time (rough: ~30 seconds per exchange)
        state.estimated_minutes_elapsed = state.messages_count * 0.25

        # Store statement for contradiction detection
        if len(participant_response) > 50:  # Only meaningful responses
            state.earlier_statements.append(participant_response[:200])
            if len(state.earlier_statements) > 10:
                state.earlier_statements = state.earlier_statements[-10:]

        # Track interviewer questions to avoid repetition (compact: first 100 chars)
        if interviewer_response:
            # Extract first sentence or truncate - keeps context compact
            question_summary = interviewer_response.split('.')[0][:100]
            state.recent_questions_asked.append(question_summary)
            # Keep last 8 questions (enough context without bloat)
            if len(state.recent_questions_asked) > 8:
                state.recent_questions_asked = state.recent_questions_asked[-8:]

        # Update topic state
        topic_id = decision.target_question_id or state.current_topic_id
        if topic_id and topic_id in state.topics:
            topic = state.topics[topic_id]
            topic.times_addressed += 1

            # Estimate depth based on response length
            words = len(participant_response.split())
            if words > 100:
                topic.depth_achieved = max(topic.depth_achieved, 3)
            elif words > 50:
                topic.depth_achieved = max(topic.depth_achieved, 2)
            else:
                topic.depth_achieved = max(topic.depth_achieved, 1)

            state.current_topic_id = topic_id

        # Handle circle back completion
        if decision.action == ProbeAction.CIRCLE_BACK and state.items_to_circle_back:
            state.items_to_circle_back.pop(0)

        return state

    def _calculate_confidence(
        self,
        signals: list[Signal],
        state: ConversationState,
    ) -> float:
        """Calculate confidence in the probe decision."""
        if not signals:
            return 0.5

        max_signal_confidence = max(s.confidence for s in signals)
        time_factor = min(1.0, state.time_remaining() / 5)

        return (max_signal_confidence + time_factor) / 2

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response text."""
        # Try to find JSON in code block
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            json_str = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            json_str = text[start:end].strip()
        else:
            # Try to find raw JSON
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = text[start:end]
            else:
                return {"signals": []}

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return {"signals": []}
