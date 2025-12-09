# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Anthropic Interviewer is an AI-powered qualitative research interview system. It conducts adaptive interviews using Claude, with real-time signal detection (emotion, novelty, discomfort, etc.) and rule-based probing decisions. The system manages the full research lifecycle: study design, rubric generation, interview execution, and transcript analysis.

## Commands

### Development Setup
```bash
# Install Python dependencies
pip install -e ".[dev]"

# Initialize database (SQLite at ./data/interviewer.db)
interviewer init

# Set API key
export ANTHROPIC_API_KEY="your-key"
```

### Running the Application
```bash
# Full stack (recommended)
./start.sh

# Or manually:
# Terminal 1 - Backend API
uvicorn src.api.main:app --reload --port 8000

# Terminal 2 - Frontend (from frontend/)
npm run dev
```

Frontend: http://localhost:5173 | Backend: http://localhost:8000 | API Docs: http://localhost:8000/docs

### CLI Commands
```bash
# Studies
interviewer study create "Study Name" --goal "Goal 1" --goal "Goal 2"
interviewer study list
interviewer study show <study_id>

# Rubrics
interviewer rubric generate <study_id>
interviewer rubric approve <rubric_id>

# Interviews
interviewer interview start <study_id> --participant "P001"
interviewer interview list <study_id>
interviewer interview transcript <interview_id>

# Analysis
interviewer analyze transcript <interview_id>
interviewer analyze study <study_id>
```

### Linting & Testing
```bash
ruff check src/
pytest
pytest tests/test_specific.py::test_function  # Single test
```

## Architecture

### Core Components

**Probing Engine** (`src/core/probing.py`): The adaptive interview intelligence.
1. **Signal Detection** (LLM) - Analyzes responses for: NOVELTY, VAGUENESS, EMOTION, CONTRADICTION, REPETITION, BREVITY, DISCOMFORT, ENTHUSIASM, TANGENT, COMPLETION
2. **Probe Decision** (Rules) - Priority-based: safety (redirect) > time pressure > high-value signals > clarification > topic exhaustion > engagement > reflect
3. **Probe Generation** (LLM) - Generates natural interviewer responses based on decision

**Services** (`src/services/`):
- `planning.py` - Study/rubric CRUD and LLM-based rubric generation
- `interview.py` - Interview execution loop, state management, probing orchestration
- `analysis.py` - Transcript coding and cross-interview theme synthesis

**API** (`src/api/main.py`): FastAPI REST endpoints for all operations

**Frontend** (`frontend/src/App.jsx`): React SPA with SetupView (study/rubric management) and InterviewView (chat interface with optional probing analysis display)

### Data Flow

```
Study → Rubric (LLM-generated) → Interview → Messages + ProbeDecisions → Analysis + Codes → Codebook + Themes
```

### Key Models

**Database** (`src/db/models.py`): SQLAlchemy ORM
- Study (1:N) Rubric (1:N) RubricSection (1:N) RubricQuestion
- Study (1:N) Interview (1:N) Message (1:1) ProbeDecisionRecord
- Interview (1:1) Analysis (1:N) Code
- Study (1:N) Codebook (1:N) Theme (hierarchical)

**Pydantic** (`src/core/models.py`): API/service layer validation
- StudyConfig, InterviewRubric, InterviewSection, Question
- ConversationState (tracks coverage, depth, time, themes)
- Signal, ProbeDecision, ProbeAction (enum)

### Interview State Tracking

`ConversationState` persisted as JSON in Interview.conversation_state:
- `topics`: dict mapping question_id to {coverage, depth, key_points}
- `current_topic_id`: active question
- `estimated_minutes_elapsed`: ~30 sec per exchange
- `themes_emerged`, `items_to_circle_back`, `participant_style`
- `earlier_statements`: last 10 for contradiction detection

## Key Patterns

- **Hybrid AI/Rules**: LLM for content analysis/generation, deterministic rules for decisions
- **Python 3.9 compatibility**: Uses `from __future__ import annotations` throughout
- **State persistence**: ConversationState stored as JSON blob, cached in InterviewService._state_cache
- **Vite proxy**: Frontend `/api` routes proxy to `http://localhost:8000`
