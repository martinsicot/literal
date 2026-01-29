# Task Plan: Literal - i+1 Sentence Builder Application

## Goal
Build a Python application that generates comprehensible sentences using vocabulary from Anki decks, applying the i+1 method where sentences contain mostly known words plus one new word to optimize language acquisition through active recall.

## Phases

### Phase 1: Research ✅
- [x] Research i+1 method and Krashen's Input Hypothesis
- [x] Understand SM-2 spaced repetition algorithm
- [x] Document computational model for word mastery levels

### Phase 2: Architecture ✅
- [x] Choose technology stack (FastAPI, SQLAlchemy, HTMX)
- [x] Design database schema
- [x] Define mastery level thresholds

### Phase 3: Project Setup & Models ✅
- [x] Create project structure
- [x] Set up pyproject.toml with dependencies
- [x] Create configuration module
- [x] Implement SQLAlchemy models (Word, UserWordState, Sentence, Review)
- [x] Create database initialization and migrations
- [x] Write model unit tests

### Phase 4: Anki Importer ✅
- [x] Research .apkg file structure (SQLite in ZIP)
- [x] Implement apkg extractor
- [x] Parse notes table for vocabulary
- [x] Parse revlog for review history
- [x] Calculate initial SM-2 state from history
- [x] Build import API endpoint

### Phase 5: SM-2 Service ✅
- [x] Implement SM-2 algorithm core
- [x] Calculate mastery levels from state
- [x] Create word selection algorithm (for i+1)
- [x] Implement review recording
- [x] Write SM-2 service tests

### Phase 6: Sentence Generation ✅
- [x] Design OpenAI prompt template
- [x] Implement sentence generation service
- [x] Add context word selection logic
- [x] Handle API errors and retries
- [x] Store generated sentences in database

### Phase 7: API Endpoints ✅
- [x] GET /words - list words with mastery
- [x] POST /import - upload Anki deck
- [x] GET /session - get next sentence for review
- [x] POST /review - record review result
- [x] GET /stats - learning statistics
- [x] POST /users - create user
- [x] GET /users/{id} - get user

### Phase 8: Web Interface ✅
- [x] Create base template with HTMX
- [x] Build word list view
- [x] Build review session interface
- [x] Build statistics dashboard
- [x] Add import functionality
- [x] Style with minimal CSS

### Phase 9: Testing & Documentation ✅
- [x] Model unit tests
- [x] SM-2 service tests
- [x] API endpoint tests

## Key Questions (All Answered)
1. ✅ i+1 method → Krashen's Input Hypothesis: ~90% known + 1 unknown word
2. ✅ Word frequency → User has existing corpus
3. ✅ Anki format → .apkg (SQLite in ZIP), parse notes/cards/revlog
4. ✅ Memorization tracking → SM-2 with mastery levels 0-4
5. ✅ Sentence complexity → 5-15 words, configurable
6. ✅ OpenAI prompt → Structured with known words + target + context requirements

## Decisions Made
| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.11+ | User requirement |
| Database | SQLite → PostgreSQL | Simple dev, scale later |
| ORM | SQLAlchemy 2.0 | Async support, migrations |
| AI Service | OpenAI GPT-4 | Best sentence quality |
| Web Framework | FastAPI | Modern, async, auto-docs |
| Frontend | HTMX + Jinja2 | Simple, progressive |
| Anki | Custom parser | Handle .apkg format |

## Mastery Levels
| Level | Name | Criteria |
|-------|------|----------|
| 0 | New | Never seen |
| 1 | Learning | interval < 7d, reps < 3 |
| 2 | Familiar | interval 7-21d |
| 3 | Known | interval > 21d, ease > 2.0 |
| 4 | Mature | interval > 60d, ease > 2.3 |

## File Structure (Completed)
```
literal/
├── src/literal/
│   ├── __init__.py          ✅
│   ├── config.py            ✅
│   ├── main.py              ✅
│   ├── models/
│   │   ├── __init__.py      ✅
│   │   ├── base.py          ✅
│   │   ├── word.py          ✅
│   │   ├── user.py          ✅
│   │   └── sentence.py      ✅
│   ├── services/
│   │   ├── __init__.py      ✅
│   │   ├── anki.py          ✅
│   │   ├── sm2.py           ✅
│   │   └── generator.py     ✅
│   ├── api/
│   │   ├── __init__.py      ✅
│   │   ├── routes.py        ✅
│   │   ├── deps.py          ✅
│   │   └── schemas.py       ✅
│   └── utils/
│       └── __init__.py      ✅
├── templates/
│   ├── base.html            ✅
│   ├── index.html           ✅
│   ├── practice.html        ✅
│   ├── words.html           ✅
│   ├── stats.html           ✅
│   └── import.html          ✅
├── static/css/
│   └── style.css            ✅
├── tests/
│   ├── __init__.py          ✅
│   ├── conftest.py          ✅
│   ├── test_models.py       ✅
│   ├── test_sm2.py          ✅
│   └── test_api.py          ✅
├── pyproject.toml           ✅
├── .env.example             ✅
├── task_plan.md             ✅
└── notes.md                 ✅
```

## How to Run

1. Install dependencies:
```bash
pip install -e ".[dev]"
```

2. Create .env file:
```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

3. Run the application:
```bash
python -m literal.main
# Or: uvicorn literal.main:app --reload
```

4. Run tests:
```bash
pytest
```

5. Access the application:
- Web UI: http://localhost:8000
- API docs: http://localhost:8000/docs

## Status
**COMPLETE** - All phases implemented and tested
