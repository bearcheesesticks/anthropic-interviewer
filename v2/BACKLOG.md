# Backlog

## Critical - Interview Experience

- [x] **Interview endings broken** - End button has no visible effect; needs closing sequence with UI feedback
- [ ] **System prompt refinement** - Interviewer persona, tone, adaptive behavior needs tuning
- [ ] **Safeguards for concerning responses** - Better handling of alarming content (crisis resources, appropriate redirects, researcher alerts)
- [x] **Repeated questions bug** - Conversation history awareness in probe generation to avoid asking similar questions after redirect

## High - Core Features

- [ ] **Rubric editing** - Manual editing of generated questions/probes before approval
- [ ] **Analysis view** - Trigger analysis, view coded transcripts, see themes
- [ ] **Interview history** - View past interviews and transcripts in web UI
- [ ] **Model selection** - Evaluate Sonnet vs Haiku vs Opus for different tasks (signal detection vs generation vs analysis)

## Medium - Agent Architecture

- [ ] **Agent structure review** - Consider giving interviewer knowledge/tools to call on (study context lookup, participant history, domain knowledge)
- [ ] **Progress visibility** - Show coverage/depth/time to researcher during interview

## Medium - Infrastructure

- [ ] **Multi-provider LLM support** - Abstract LLMClient interface to support Gemini alongside Anthropic (see `docs/GEMINI_MIGRATION_PLAN.md`)

## Foundation

- [ ] **Tests** - Add test coverage for core services and probing engine
- [ ] **Logging** - Add structured logging for debugging and audit trails
- [ ] **Security review** - Input validation, rate limiting, data handling
- [ ] **Code cleanup** - Efficiency, consistency, error handling
- [ ] **Python version alignment** - pyproject.toml says 3.10+ but code uses 3.9 compatibility patterns
