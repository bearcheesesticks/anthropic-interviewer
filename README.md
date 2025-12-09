# Anthropic Interviewer

AI-powered qualitative research interview system. Conducts adaptive interviews using Claude with real-time signal detection and intelligent probing.

## Features

- Adaptive interview flow with signal detection (emotion, novelty, vagueness, etc.)
- Rule-based probing decisions to deepen responses
- Study design and rubric generation
- Transcript analysis and theme synthesis
- Web UI and CLI interfaces

## Quick Start

```bash
# Clone and enter directory
cd anthropic-interviewer/v2

# Set your API key
export ANTHROPIC_API_KEY="your-key"

# Install Python dependencies
pip install -e ".[dev]"

# Initialize database
python -m src.cli.main init

# Start the app (backend + frontend)
./start.sh
```

Then open http://localhost:5173

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed system design.

```
v2/
├── src/
│   ├── api/        # FastAPI REST endpoints
│   ├── core/       # Probing engine, models
│   ├── db/         # SQLAlchemy models
│   └── services/   # Planning, interview, analysis
├── frontend/       # React + Vite
└── start.sh        # Dev startup script
```

## CLI Usage

```bash
# Create a study
interviewer study create "My Study" --goal "Understand X"

# Generate interview rubric
interviewer rubric generate <study_id>

# Run interview
interviewer interview start <study_id> --participant "P001"

# Analyze results
interviewer analyze study <study_id>
```

## Development

```bash
# Lint
ruff check src/

# Test
pytest
```
