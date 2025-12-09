# Anthropic Interviewer: Architecture Document

## Executive Summary

Anthropic Interviewer is a multi-agent system for conducting qualitative research interviews at scale. It combines the depth of human interviews with the scale of automated surveys by using Claude to plan, conduct, and analyze interviews adaptively.

This document defines the complete system architecture, component interactions, and implementation approach.

---

## 1. System Overview

### 1.1 Core Value Proposition

Traditional trade-off:
- **Surveys**: Scale to thousands, but shallow data
- **Interviews**: Deep insights, but expensive and limited scale

Anthropic Interviewer provides: **Deep qualitative data at survey scale**

### 1.2 Three-Stage Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PLANNING STAGE                                  │
│  Research Goals → Interview Rubric → Human Review → Approved Rubric         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            INTERVIEWING STAGE                                │
│  For each participant:                                                       │
│  Rubric + Context → Adaptive Interview → Probing Decisions → Transcript     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             ANALYSIS STAGE                                   │
│  Transcripts → Individual Coding → Theme Synthesis → Research Findings      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Key Design Principles

1. **Human-in-the-loop** - Humans review rubrics before deployment, validate themes after analysis
2. **Adaptive interviewing** - Real-time decisions about when to probe deeper vs. move on
3. **Consistent at scale** - Same research questions explored consistently across hundreds of interviews
4. **Emergent discovery** - System surfaces unexpected themes, not just confirms hypotheses

---

## 2. Component Architecture

### 2.1 Planning System

**Purpose**: Transform research goals into a structured interview rubric.

```
┌─────────────────────────────────────────────────────────────────┐
│                      PLANNING SYSTEM                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   Research   │───▶│   Rubric     │───▶│   Human      │       │
│  │   Config     │    │   Generator  │    │   Review     │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│                                                 │                │
│  Inputs:                                        ▼                │
│  - Research goals            ┌──────────────────────────────┐   │
│  - Target population         │     Approved Rubric          │   │
│  - Hypotheses (optional)     │  - Sections & questions      │   │
│  - Duration target           │  - Probes per question       │   │
│  - Special considerations    │  - Interviewer guidance      │   │
│                              │  - Skip logic                │   │
│                              └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**Rubric Schema**:
```
Rubric
├── metadata
│   ├── study_title
│   ├── research_goals[]
│   ├── target_duration_minutes
│   └── version
├── sections[]
│   ├── name
│   ├── purpose
│   ├── questions[]
│   │   ├── id
│   │   ├── text
│   │   ├── purpose
│   │   ├── probes[]
│   │   ├── skip_if (optional)
│   │   └── required_depth (1-3)
│   └── transition_guidance
└── interviewer_guidance
    ├── tone
    ├── pacing
    ├── sensitive_topics[]
    ├── probing_strategy
    └── closing_approach
```

**Key Decisions**:
- How much structure vs. flexibility in the rubric?
- Should rubrics support branching logic (if answer X, ask Y)?
- How to handle multiple target populations with one rubric?

### 2.2 Interview System

**Purpose**: Conduct adaptive, real-time interviews that feel natural while ensuring research coverage.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INTERVIEW SYSTEM                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    INTERVIEW CONTROLLER                              │    │
│  │  Orchestrates the interview flow and manages state                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│           │                    │                      │                      │
│           ▼                    ▼                      ▼                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  CONVERSATION   │  │    PROBING      │  │     STATE       │             │
│  │    AGENT        │  │    ENGINE       │  │    TRACKER      │             │
│  │                 │  │                 │  │                 │             │
│  │ Generates       │  │ Detects signals │  │ Tracks:         │             │
│  │ natural         │  │ Decides action  │  │ - Coverage      │             │
│  │ responses       │  │ Suggests probe  │  │ - Depth         │             │
│  │                 │  │                 │  │ - Time          │             │
│  └─────────────────┘  └─────────────────┘  │ - Themes        │             │
│                                            │ - Circle-backs  │             │
│                                            └─────────────────┘             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 2.2.1 Probing Engine (Critical Component)

The probing engine is the core intelligence that makes interviews adaptive.

**Signal Detection**:
| Signal | Description | Detection Approach |
|--------|-------------|-------------------|
| NOVELTY | Unexpected/unique content | LLM evaluates against research goals |
| VAGUENESS | Abstract, needs grounding | Looks for generalizations, lack of examples |
| EMOTION | Strong feeling expressed | Emphatic language, personal stakes |
| CONTRADICTION | Conflicts with earlier statement | Compare against conversation history |
| REPETITION | Rehashing same points | Semantic similarity to previous responses |
| BREVITY | Unusually short response | Token count + context expectations |
| DISCOMFORT | Signs of unease | Hedging, deflection, topic avoidance |
| ENTHUSIASM | High engagement | Long responses, unsolicited detail |
| TANGENT | Off-topic but valuable | Relevant to research but not current question |
| COMPLETION | Topic fully explored | Summary statements, natural closure |

**Probe Actions**:
| Action | When to Use | Example |
|--------|-------------|---------|
| PROBE_DEEPER | High-value signal detected | "Can you tell me more about that specific moment?" |
| FOLLOW_UP | Related angle worth exploring | "How does that connect to your daily workflow?" |
| CLARIFY | Vague or contradictory response | "When you say 'sometimes', what do you mean exactly?" |
| REFLECT | Validate before continuing | "So it sounds like you feel... Is that right?" |
| MOVE_ON | Topic exhausted or time pressure | "That's really helpful. I'm curious about..." |
| CIRCLE_BACK | Return to noted tangent | "Earlier you mentioned X. Tell me more about that." |
| REDIRECT | Discomfort detected | "I appreciate you sharing. Let's talk about..." |
| CLOSE | Time up or coverage complete | "Before we wrap up, anything else to add?" |

**Decision Priority Logic**:
```
1. DISCOMFORT detected (confidence > 0.6) → REDIRECT (participant wellbeing first)
2. Time pressure + low coverage → MOVE_ON (ensure breadth)
3. NOVELTY or EMOTION (confidence > 0.7) → PROBE_DEEPER (high-value signals)
4. VAGUENESS or CONTRADICTION → CLARIFY (resolve ambiguity)
5. COMPLETION or REPETITION → MOVE_ON or CIRCLE_BACK
6. ENTHUSIASM → FOLLOW_UP (ride the engagement)
7. Default → REFLECT + continue
```

#### 2.2.2 Conversation State

```
ConversationState
├── topics: Map<topic_id, TopicState>
│   ├── times_addressed: int
│   ├── depth_achieved: 0-3
│   ├── key_points: string[]
│   └── needs_revisit: bool
├── current_topic_id: string
├── messages_count: int
├── estimated_time_elapsed: float
├── target_duration: int
├── themes_emerged: string[]
├── items_to_circle_back: Queue
├── participant_style: string  // verbose, concise, tangential
└── earlier_statements: string[]  // for contradiction detection
```

### 2.3 Analysis System

**Purpose**: Extract themes from transcripts and synthesize research findings.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            ANALYSIS SYSTEM                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1: Individual Transcript Analysis                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ Transcript  │───▶│  Coding     │───▶│  Coded      │                      │
│  │             │    │  Agent      │    │  Transcript │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
│                                                                              │
│  PHASE 2: Codebook Development (after N transcripts)                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ Initial     │───▶│  Codebook   │───▶│  Stable     │                      │
│  │ Codes       │    │  Refinement │    │  Codebook   │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
│                           │                                                  │
│                           ▼                                                  │
│                    Human Review                                              │
│                                                                              │
│  PHASE 3: Scaled Coding (apply codebook consistently)                        │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ Remaining   │───▶│  Apply      │───▶│  All Coded  │                      │
│  │ Transcripts │    │  Codebook   │    │  Transcripts│                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
│                                                                              │
│  PHASE 4: Theme Synthesis                                                    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ All Coded   │───▶│  Theme      │───▶│  Research   │                      │
│  │ Transcripts │    │  Synthesis  │    │  Findings   │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Analysis Outputs**:

1. **Individual Transcript Analysis**:
   - Summary (2-3 sentences)
   - Codes applied with quotation evidence
   - Notable insights
   - Research question relevance mapping

2. **Codebook**:
   - Code definitions
   - Inclusion/exclusion criteria
   - Example quotations
   - Hierarchical structure (codes → themes)

3. **Theme Analysis**:
   - Theme name and description
   - Prevalence (% of participants)
   - Sub-themes
   - Supporting evidence (quotes + transcript IDs)
   - Variation across participant groups

4. **Research Findings**:
   - Answers to research questions
   - Confidence levels
   - Evidence summaries
   - Unexpected discoveries
   - Limitations

### 2.4 Storage System

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            STORAGE SYSTEM                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  /data                                                                       │
│  └── {study_name}/                                                           │
│      ├── config/                                                             │
│      │   ├── study_config.json      # Research goals, population, etc.      │
│      │   └── rubric_v{n}.json       # Versioned rubrics                     │
│      │                                                                       │
│      ├── transcripts/                                                        │
│      │   ├── {session_id}.json      # Individual transcripts                │
│      │   └── transcripts.parquet    # Batch export (Anthropic format)       │
│      │                                                                       │
│      ├── analyses/                                                           │
│      │   ├── individual/                                                     │
│      │   │   └── {session_id}_analysis.json                                 │
│      │   ├── codebook_v{n}.json     # Versioned codebooks                   │
│      │   └── themes_{timestamp}.json                                        │
│      │                                                                       │
│      └── exports/                                                            │
│          ├── report_{timestamp}.md                                           │
│          └── data_{timestamp}.csv                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. User Interfaces

### 3.1 CLI Interface

```
anthropic-interviewer
├── plan
│   ├── create          # Interactive rubric creation
│   ├── review          # Review/edit existing rubric
│   └── export          # Export rubric to file
│
├── interview
│   ├── start           # Begin new interview session
│   ├── resume          # Resume interrupted session
│   └── batch           # Run multiple interviews (for testing)
│
├── analyze
│   ├── transcript      # Analyze single transcript
│   ├── batch           # Analyze all transcripts
│   ├── codebook        # Develop/refine codebook
│   └── synthesize      # Generate theme synthesis
│
└── export
    ├── parquet         # Export to Anthropic's format
    ├── report          # Generate research report
    └── quotes          # Extract quotations by theme
```

### 3.2 Interactive Interview UI

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  🎙️ Interview: AI Usage Study                          ⏱️ 7:32 / 15:00      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ 🎤 Interviewer:                                                      │    │
│  │                                                                      │    │
│  │ That's fascinating that you've noticed changes in how your team     │    │
│  │ makes decisions. Can you walk me through a specific example where   │    │
│  │ AI influenced a decision that used to involve more debate?          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ You: _                                                               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  📊 Progress                           🧠 Last Decision                      │
│  ━━━━━━━━━━━━━━━━━━░░░░░ 65%          PROBE_DEEPER                          │
│  Coverage: 4/7 topics                  "Novel insight about team dynamics"  │
│  Depth: 2.3/3.0 avg                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  🔍 Signals: NOVELTY (0.8) • ENTHUSIASM (0.7)                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Analysis Dashboard (Future)

- Transcript browser with search
- Theme visualization
- Quote extraction interface
- Codebook editor
- Report generator

---

## 4. Data Flow

### 4.1 Complete Pipeline

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Researcher │     │    System    │     │ Participants │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       │ Define goals       │                    │
       │───────────────────▶│                    │
       │                    │                    │
       │ Generate rubric    │                    │
       │◀───────────────────│                    │
       │                    │                    │
       │ Review & approve   │                    │
       │───────────────────▶│                    │
       │                    │                    │
       │                    │ Conduct interview  │
       │                    │◀──────────────────▶│
       │                    │    (N times)       │
       │                    │                    │
       │                    │ Store transcripts  │
       │                    │───────────────────▶│ (storage)
       │                    │                    │
       │ Review sample      │                    │
       │◀───────────────────│                    │
       │                    │                    │
       │                    │ Develop codebook   │
       │                    │───────────────────▶│ (storage)
       │                    │                    │
       │ Review codebook    │                    │
       │◀───────────────────│                    │
       │                    │                    │
       │ Approve codebook   │                    │
       │───────────────────▶│                    │
       │                    │                    │
       │                    │ Analyze all        │
       │                    │───────────────────▶│ (storage)
       │                    │                    │
       │                    │ Synthesize themes  │
       │                    │───────────────────▶│ (storage)
       │                    │                    │
       │ Review findings    │                    │
       │◀───────────────────│                    │
       │                    │                    │
       ▼                    ▼                    ▼
```

### 4.2 Interview Session Flow

```
START
  │
  ▼
┌─────────────────┐
│ Load rubric &   │
│ initialize state│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Generate opening│
│ message         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│ Wait for        │◀────│ Display         │
│ participant     │     │ interviewer msg │
└────────┬────────┘     └─────────────────┘
         │                      ▲
         ▼                      │
┌─────────────────┐             │
│ Receive         │             │
│ response        │             │
└────────┬────────┘             │
         │                      │
         ▼                      │
┌─────────────────┐             │
│ Detect signals  │             │
└────────┬────────┘             │
         │                      │
         ▼                      │
┌─────────────────┐             │
│ Update state    │             │
└────────┬────────┘             │
         │                      │
         ▼                      │
┌─────────────────┐             │
│ Decide probe    │             │
│ action          │             │
└────────┬────────┘             │
         │                      │
         ▼                      │
┌─────────────────┐             │
│ Should end?     │             │
└────────┬────────┘             │
         │                      │
    No   │   Yes                │
    ┌────┴────┐                 │
    │         │                 │
    ▼         ▼                 │
┌───────┐ ┌─────────┐           │
│Generate│ │Generate │           │
│response│ │closing  │           │
└───┬───┘ └────┬────┘           │
    │          │                │
    │          ▼                │
    │     ┌─────────┐           │
    │     │ Save    │           │
    │     │transcript│          │
    │     └────┬────┘           │
    │          │                │
    │          ▼                │
    │        END                │
    │                           │
    └───────────────────────────┘
```

---

## 5. Technical Decisions

### 5.1 Model Selection

| Component | Recommended Model | Rationale |
|-----------|------------------|-----------|
| Rubric Generation | Opus/Sonnet | Complex reasoning, one-time cost |
| Interview Conversation | Sonnet | Balance of quality and latency |
| Signal Detection | Haiku/Sonnet | Fast, frequent calls |
| Probe Generation | Haiku | Fast, constrained output |
| Transcript Analysis | Sonnet | Quality matters, batch processing |
| Theme Synthesis | Opus | Complex reasoning across many inputs |

### 5.2 Latency Considerations

Interview latency budget (target: < 3 seconds total):
- Signal detection: ~500ms (Haiku, parallel with response)
- Probe decision: ~100ms (rule-based + light LLM)
- Response generation: ~1500ms (Sonnet)
- State update: ~50ms (local)

Optimization strategies:
- Prefetch next likely question while participant types
- Cache signal detection prompts
- Use streaming for response generation

### 5.3 Scale Considerations

For studies with 100+ interviews:
- Parallel interview sessions (async)
- Batch transcript analysis (parallel workers)
- Codebook consistency checks
- Theme prevalence statistical validation

### 5.4 Error Handling

| Error Type | Handling Strategy |
|------------|-------------------|
| API timeout | Retry with backoff, save partial state |
| Malformed response | Fallback to safe probe action |
| Participant disconnect | Save partial transcript, allow resume |
| Analysis inconsistency | Flag for human review |

---

## 6. Implementation Phases

### Phase 1: Core Interview Loop (MVP++)
- Rubric generation with human review
- Adaptive interview with full probing logic
- Real-time signal detection and display
- Transcript storage

### Phase 2: Analysis Pipeline
- Individual transcript coding
- Codebook development workflow
- Theme synthesis
- Basic reporting

### Phase 3: Scale & Polish
- Parallel interviews
- Batch analysis
- Web interface
- Export formats (Parquet, reports)

### Phase 4: Advanced Features
- Multi-population studies
- Longitudinal studies
- Real-time theme monitoring during data collection
- Integration with existing research tools

---

## 7. Design Decisions (Resolved)

### Architecture Decisions

1. **Probing Decision Architecture**: LLM signal detection + rule-based decisions
   - LLM detects signals in responses (novelty, emotion, vagueness, etc.)
   - Rules determine action based on signals + conversation state
   - Rationale: Balance of adaptability and consistency

2. **Single Agent for Interviews**: Single agent with probing logic embedded
   - Simpler architecture, easier to maintain
   - Probing engine as internal component, not separate agent

3. **Analysis Consistency**: Standard human review
   - Review rubric before deployment
   - Review codebook after initial development
   - Review final themes before reporting
   - Codebook locks after review, flags new codes for human decision

### UX Decisions

4. **Interface**: CLI + Web UI
   - CLI for development, testing, and power users
   - Web UI (FastAPI + React) for real participant interviews
   - Same backend, different frontends

5. **Probing Transparency**: Optional toggle
   - Hidden by default for clean participant experience
   - Can be enabled for demos, researcher monitoring, or transparency
   - Researcher dashboard always shows full analysis

6. **Researcher Workflow**: Direct editing
   - Full control over rubric structure
   - Can edit codebook directly (with version history)
   - Theme synthesis with human refinement step

### Technical Decisions

7. **Storage**: SQLite database
   - Queryable, handles relationships
   - Single file, easy to backup/share
   - Export to Parquet/JSON for compatibility

8. **Target Scale**: Small studies (10-100 interviews)
   - No need for heavy parallelism optimization
   - Focus on quality over throughput
   - Can run multiple interviews sequentially

9. **Deployment**: Local-first
   - Run locally with user's API key
   - Single-user by default
   - Web UI runs on localhost

---

## 8. Success Metrics

### Interview Quality
- Topic coverage rate (target: >80% of rubric questions addressed)
- Average depth per topic (target: 2.0+/3.0)
- Participant engagement (response length, unsolicited elaboration)
- Signal detection accuracy (validated against human coding)

### Analysis Quality
- Inter-coder reliability (if multiple coders)
- Theme coherence (human evaluation)
- Research question coverage
- Unexpected insight rate

### System Performance
- Interview latency (target: <3s per response)
- Analysis throughput (transcripts per hour)
- Error rate (<1% failed interviews)

---

## Appendix A: Example Rubric

```json
{
  "study_title": "AI Integration in Knowledge Work",
  "research_goals": [
    "Understand how professionals integrate AI tools into daily work",
    "Identify pain points and satisfactions with current AI tools",
    "Explore concerns about AI's impact on their profession"
  ],
  "target_duration_minutes": 15,
  "sections": [
    {
      "name": "Opening & Context",
      "purpose": "Build rapport and establish participant background",
      "questions": [
        {
          "id": "Q1",
          "text": "Tell me about your role and the kind of work you do day-to-day.",
          "purpose": "Establish context for AI usage",
          "probes": [
            "What does a typical day look like?",
            "What are the most important outputs of your work?"
          ],
          "required_depth": 1
        }
      ]
    },
    {
      "name": "AI Usage Patterns",
      "purpose": "Understand concrete AI integration",
      "questions": [
        {
          "id": "Q2",
          "text": "Walk me through how AI tools fit into your work. What do you use them for?",
          "purpose": "Map AI touchpoints",
          "probes": [
            "Can you give me a specific example from this week?",
            "What does the interaction actually look like?",
            "How did you decide to use AI for that vs. doing it yourself?"
          ],
          "required_depth": 3
        }
      ]
    }
  ],
  "interviewer_guidance": {
    "tone": "Warm, curious, non-judgmental",
    "pacing": "Allow silence for reflection, don't rush",
    "sensitive_topics": ["job security concerns", "mistakes made with AI"],
    "probing_strategy": "Prioritize concrete examples over abstract opinions",
    "closing_approach": "Always offer chance to add anything not covered"
  }
}
```

## Appendix B: Signal Detection Prompt Template

```
Analyze this interview exchange and detect signals:

## Context
Research Goal: {research_goal}
Current Topic: {current_topic}
Time Remaining: {time_remaining} minutes

## Recent Exchange
{exchange}

## Signals to Detect
[NOVELTY, VAGUENESS, EMOTION, CONTRADICTION, REPETITION,
 BREVITY, DISCOMFORT, ENTHUSIASM, TANGENT, COMPLETION]

For each detected signal, provide:
- signal_type
- confidence (0-1)
- evidence (exact quote)
- suggested_action

Return JSON array of signals, ordered by importance.
```

## Appendix C: Comparison with Anthropic's Implementation

| Aspect | Anthropic's System | Our Implementation |
|--------|-------------------|-------------------|
| Scale achieved | 1,250 interviews | Target: 100+ |
| Analysis tool | Clio (privacy-preserving) | Custom theme synthesis |
| Interview duration | 10-15 minutes | Configurable |
| Deployment | claude.ai integration | Standalone CLI/web |
| Human checkpoints | Rubric review, analysis review | Same + codebook review |
