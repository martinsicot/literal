# Literal - i+1 Sentence Builder for Language Learning

Literal is an application that generates comprehensible sentences using vocabulary from Anki decks, applying the **i+1 method** where sentences contain mostly known words plus one new word to optimize language acquisition through active recall.

## Features

- **i+1 Method**: Sentences are generated with ~90% known words + 1 unknown word
- **Spaced Repetition**: SM-2 algorithm tracks your progress and schedules reviews
- **Anki Integration**: Import your existing Anki decks with review history
- **AI-Generated Sentences**: Natural sentences created by OpenAI that use your vocabulary
- **Multi-Language**: Supports Basque, English, Spanish, French, German (extensible)

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- OpenAI API key

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd literal

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"
```

### Configuration

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and add your OpenAI API key
OPENAI_API_KEY=sk-your-api-key-here
```

### Running the Application

```bash
# Start the server
python -m literal.main

# Or with uvicorn
uvicorn literal.main:app --reload
```

Access the application:
- **Web UI**: http://localhost:8000
- **API docs**: http://localhost:8000/docs

### Running Tests

```bash
pytest
```

## How It Works

### The i+1 Method

Based on Stephen Krashen's **Input Hypothesis**, the i+1 method suggests that language acquisition happens when learners are exposed to input that is slightly beyond their current competence level:

- **i** = current proficiency level (what you already know)
- **+1** = one level beyond current (introduces ONE new element)

Literal generates sentences that:
- Contain mostly words you already know (context)
- Introduce exactly ONE new word (the target)
- Make the target word's meaning inferrable from context

### Mastery Levels

| Level | Name | Criteria |
|-------|------|----------|
| 0 | New | Never seen |
| 1 | Learning | interval < 7 days |
| 2 | Familiar | interval 7-21 days |
| 3 | Known | interval > 21 days, ease > 2.0 |
| 4 | Mature | interval > 60 days, ease > 2.3 |

### SM-2 Algorithm

Literal uses the SM-2 spaced repetition algorithm (used by Anki) to:
- Track your knowledge of each word
- Schedule optimal review times
- Adjust difficulty based on your recall performance

## Project Structure

```
literal/
├── src/literal/
│   ├── models/      # SQLAlchemy database models
│   ├── services/    # Business logic (SM-2, Anki import, sentence generation)
│   ├── api/         # FastAPI routes and schemas
│   └── main.py      # Application entry point
├── templates/       # Jinja2 HTML templates
├── static/          # CSS and JS files
├── tests/           # pytest test suite
└── pyproject.toml   # Project configuration
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/users | Create a new user |
| GET | /api/users/{id} | Get user details |
| GET | /api/words | List words with mastery info |
| POST | /api/words | Create a new word |
| POST | /api/import | Import an Anki deck |
| GET | /api/session | Get next sentence for practice |
| POST | /api/reviews | Record a review |
| GET | /api/stats | Get learning statistics |

## Technology Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0
- **Database**: SQLite (dev), PostgreSQL-ready
- **Frontend**: HTMX, Jinja2
- **AI**: OpenAI GPT-4
- **Testing**: pytest, pytest-asyncio

## License

MIT
