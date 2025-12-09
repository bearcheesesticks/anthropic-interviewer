# Gemini API Migration Plan

## Current State

The codebase uses the Anthropic SDK directly in 4 files with 6 total LLM calls:

| File | Method | System Prompt? | Purpose |
|------|--------|----------------|---------|
| `src/core/probing.py` | `detect_signals()` | No | Signal detection |
| `src/core/probing.py` | `generate_probe()` | No | Generate interviewer response |
| `src/services/planning.py` | `generate_rubric()` | No | Generate interview rubric |
| `src/services/interview.py` | `_generate_opening()` | Yes | Generate opening message |
| `src/services/analysis.py` | `analyze_transcript()` | No | Code transcript |
| `src/services/analysis.py` | `synthesize_themes()` | No | Cross-interview synthesis |

### Current Anthropic Pattern
```python
from anthropic import Anthropic

client = Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    system="optional system prompt",  # only used in interview.py
    messages=[{"role": "user", "content": prompt}],
)
text = response.content[0].text
```

### Gemini Equivalent
```python
from google import genai
from google.genai import types

client = genai.Client(api_key="...")
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction="optional system prompt",
        max_output_tokens=1024,
    ),
)
text = response.text
```

## Key API Differences

| Aspect | Anthropic | Gemini |
|--------|-----------|--------|
| Package | `anthropic` | `google-genai` |
| Client | `Anthropic()` | `genai.Client(api_key=...)` |
| Method | `client.messages.create()` | `client.models.generate_content()` |
| System prompt | `system=` parameter | `config.system_instruction` |
| Max tokens | `max_tokens=` | `config.max_output_tokens` |
| Messages | `messages=[{"role":..., "content":...}]` | `contents=` (string or list) |
| Response text | `response.content[0].text` | `response.text` |
| Auth | `ANTHROPIC_API_KEY` env var | `GOOGLE_API_KEY` or explicit |

## Implementation Options

### Option A: Abstract LLM Client (Recommended)

Create a provider-agnostic interface:

```python
# src/core/llm.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class LLMResponse:
    text: str
    model: str
    usage: Optional[dict] = None

class LLMClient(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        pass

class AnthropicClient(LLMClient):
    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        from anthropic import Anthropic
        self.client = Anthropic()
        self.model = model

    def generate(self, prompt, *, system=None, max_tokens=1024):
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        response = self.client.messages.create(**kwargs)
        return LLMResponse(
            text=response.content[0].text,
            model=self.model,
            usage={"input": response.usage.input_tokens, "output": response.usage.output_tokens},
        )

class GeminiClient(LLMClient):
    def __init__(self, model: str = "gemini-2.5-flash"):
        from google import genai
        from google.genai import types
        self.client = genai.Client()
        self.model = model
        self.types = types

    def generate(self, prompt, *, system=None, max_tokens=1024):
        config = self.types.GenerateContentConfig(max_output_tokens=max_tokens)
        if system:
            config.system_instruction = system

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return LLMResponse(
            text=response.text,
            model=self.model,
            usage=None,  # Gemini usage tracking differs
        )
```

**Pros:**
- Clean separation of concerns
- Easy to add more providers (OpenAI, Mistral, etc.)
- Testable with mock clients
- Provider-specific features can be added to subclasses

**Cons:**
- Requires refactoring all 4 files
- ~2-3 hours of work

### Option B: Adapter Pattern (Quick & Dirty)

Create a drop-in replacement that mimics Anthropic's API:

```python
# src/core/llm_adapter.py
class GeminiAsAnthropic:
    """Adapter that makes Gemini look like Anthropic SDK."""

    def __init__(self):
        from google import genai
        self.client = genai.Client()
        self.messages = self  # self.messages.create() pattern

    def create(self, model, max_tokens, messages, system=None):
        from google.genai import types

        # Convert messages to Gemini format
        prompt = messages[0]["content"]  # Simplified

        config = types.GenerateContentConfig(max_output_tokens=max_tokens)
        if system:
            config.system_instruction = system

        response = self.client.models.generate_content(
            model=self._map_model(model),
            contents=prompt,
            config=config,
        )

        # Return Anthropic-like response
        return _FakeResponse(response.text)

    def _map_model(self, anthropic_model):
        mapping = {
            "claude-sonnet-4-20250514": "gemini-2.5-flash",
            "claude-opus-4-20250514": "gemini-2.5-pro",
        }
        return mapping.get(anthropic_model, "gemini-2.5-flash")

class _FakeResponse:
    def __init__(self, text):
        self.content = [type('obj', (object,), {'text': text})]
```

**Pros:**
- Minimal code changes (just swap import)
- Can be done in 30 minutes

**Cons:**
- Hacky, harder to maintain
- Doesn't expose Gemini-specific features
- Model mapping is fragile

### Option C: Use LiteLLM

Use [LiteLLM](https://github.com/BerriAI/litellm) for unified API:

```python
import litellm

response = litellm.completion(
    model="gemini/gemini-2.5-flash",  # or "claude-3-sonnet"
    messages=[{"role": "user", "content": prompt}],
    max_tokens=1024,
)
text = response.choices[0].message.content
```

**Pros:**
- Immediate 100+ provider support
- Active community, well-maintained
- Handles rate limiting, retries

**Cons:**
- Large dependency (~50+ transitive deps)
- Less control over provider-specific features
- OpenAI-style response format (different from current)

## Recommended Approach

**Option A (Abstract LLM Client)** is recommended because:

1. This codebase is already well-structured with dependency injection
2. You may want provider-specific features (Gemini's grounding, Claude's artifacts)
3. Testing becomes easier with mock clients
4. No external dependencies beyond the provider SDKs

## Implementation Steps

1. **Create `src/core/llm.py`** with `LLMClient` interface and `AnthropicClient`
2. **Update services** to accept `LLMClient` instead of `Anthropic`
3. **Add `GeminiClient`** implementation
4. **Add config** for provider selection (env var or config file)
5. **Update API/CLI** to instantiate correct client based on config

### File Changes Required

```
src/core/llm.py          # NEW - LLMClient interface + implementations
src/core/probing.py      # Change Anthropic → LLMClient
src/services/planning.py # Change Anthropic → LLMClient
src/services/interview.py# Change Anthropic → LLMClient
src/services/analysis.py # Change Anthropic → LLMClient
src/api/main.py          # Update client instantiation
src/cli/main.py          # Update client instantiation
pyproject.toml           # Add google-genai to optional deps
```

## Model Mapping

| Use Case | Anthropic | Gemini |
|----------|-----------|--------|
| Fast/cheap (probing, signals) | claude-sonnet-4-20250514 | gemini-2.5-flash |
| Quality (analysis) | claude-sonnet-4-20250514 | gemini-2.5-pro |
| Best (complex synthesis) | claude-opus-4-20250514 | gemini-2.5-pro |

## Environment Variables

```bash
# Current
ANTHROPIC_API_KEY=sk-ant-...

# With Gemini support
LLM_PROVIDER=gemini  # or "anthropic" (default)
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AI...
```

## Sources

- [Google Gen AI SDK documentation](https://googleapis.github.io/python-genai/)
- [Gemini API quickstart](https://ai.google.dev/gemini-api/docs/quickstart)
- [google-genai PyPI](https://pypi.org/project/google-genai/)
