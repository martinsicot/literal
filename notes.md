# Research Notes: Literal - i+1 Sentence Builder

## Sources

### i+1 / Comprehensible Input Theory
- [Krashen's Input Hypothesis - Wikipedia](https://en.wikipedia.org/wiki/Input_hypothesis)
- [Mango Languages - Krashen's i+1](https://blog.mangolanguages.com/krashens-input-hypothesis-and-comprehensible-input-i-1/)
- [Taalhammer - Comprehensible Input](https://www.taalhammer.com/what-is-comprehensible-input-in-language-learning-stephen-krashens-theory/)

### SM-2 Algorithm / Spaced Repetition
- [RemNote - Anki SM-2 Algorithm](https://help.remnote.com/en/articles/6026144-the-anki-sm-2-spaced-repetition-algorithm)
- [GitHub - open-spaced-repetition/anki-sm-2](https://github.com/open-spaced-repetition/anki-sm-2)
- [Tegaru - SM-2 Algorithm Explained](https://tegaru.app/en/blog/sm2-algorithm-explained)

### Basque Language Resources
- [EHME - Patterns of Frequency in Basque Lexicon](https://www.ehu.eus/en/web/eins/euskal-hiztegiaren-maiztasun-egitura-ehme-)
- [E-Hitz Research Paper](https://www.researchgate.net/publication/51377257_E-Hitz_A_word_frequency_list_and_a_program_for_deriving_psycholinguistic_statistics_in_an_agglutinative_language_Basque)
- **User has existing frequency corpus** - no need to source externally

---

## Key Concepts

### i+1 Method (Krashen's Input Hypothesis)

**Core Principle**: Language acquisition happens when learners are exposed to input that is slightly beyond their current competence level.

- **i** = current proficiency level (what learner already knows)
- **+1** = one level beyond current (introduces ONE new element)

**For Our Application**:
- A sentence should contain mostly KNOWN words
- Exactly ONE (or very few) UNKNOWN words
- The unknown word should be inferrable from context
- Focus on meaning, not grammar drilling

**Computational Model for "Known"**:
1. Word has been seen AND correctly recalled multiple times
2. SM-2 ease factor above threshold (e.g., > 2.0)
3. Interval has grown beyond learning phase (e.g., > 7 days)
4. Recent review was successful (quality >= 3)

### SM-2 Algorithm Core

**Inputs**:
- `quality`: 0-5 rating (Anki uses 4 buttons: Again/Hard/Good/Easy → mapped to 0/2/3/5)
- `repetitions`: number of successful reviews
- `ease_factor`: starts at 2.5, adjusted based on performance
- `interval`: days until next review

**Key Formula**:
```
IF quality >= 3 (correct):
  IF repetitions == 0: interval = 1 day
  IF repetitions == 1: interval = 6 days
  IF repetitions > 1: interval = previous_interval × ease_factor

new_ease_factor = ease_factor + (0.1 - (5 - quality) × (0.08 + (5 - quality) × 0.02))
ease_factor = max(1.3, new_ease_factor)  # Never below 1.3
```

**Anki Modifications**:
- 4-button system instead of 0-5
- "Easy" adds bonus to interval
- Learning phase doesn't affect ease
- Minimum interval increase of 1 day

### Word "Mastery" Levels (Our Model)

| Level | Name | Criteria | Use in Sentences |
|-------|------|----------|------------------|
| 0 | New | Never seen | Target word (the +1) |
| 1 | Learning | interval < 7 days, reps < 3 | Target word |
| 2 | Familiar | interval 7-21 days | Can be context |
| 3 | Known | interval > 21 days, ease > 2.0 | Safe for context |
| 4 | Mature | interval > 60 days, ease > 2.3 | Highly reliable |

### Sentence Generation Strategy

**Optimal i+1 Sentence**:
- 70-90% Mature/Known words (levels 3-4)
- 10-20% Familiar words (level 2)
- Exactly 1 New/Learning word (levels 0-1) as the TARGET
- Sentence length: 5-15 words (adjustable)

**OpenAI Prompt Strategy**:
```
Generate a natural [LANGUAGE] sentence that:
- Uses these KNOWN words: [list]
- Introduces this NEW word: [target_word] meaning [translation]
- The sentence should make the meaning of [target_word] clear from context
- Length: approximately [N] words
- Register: [casual/formal/neutral]
```

---

## Technical Decisions

### Database Schema Draft

```sql
-- Words table
words (
    id INTEGER PRIMARY KEY,
    word TEXT NOT NULL,
    language TEXT NOT NULL,  -- 'eu' for Basque, 'en' for English
    translation TEXT,
    frequency_rank INTEGER,  -- from corpus
    part_of_speech TEXT,
    created_at TIMESTAMP
)

-- User word state (SM-2 tracking)
user_word_state (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    word_id INTEGER REFERENCES words(id),
    repetitions INTEGER DEFAULT 0,
    ease_factor FLOAT DEFAULT 2.5,
    interval INTEGER DEFAULT 0,  -- days
    next_review DATE,
    last_review DATE,
    quality_history TEXT,  -- JSON array of recent qualities
    mastery_level INTEGER DEFAULT 0
)

-- Generated sentences
sentences (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    target_word_id INTEGER REFERENCES words(id),
    sentence_text TEXT,
    translation TEXT,
    context_word_ids TEXT,  -- JSON array
    generated_at TIMESTAMP,
    reviewed BOOLEAN DEFAULT FALSE,
    feedback_rating INTEGER  -- user satisfaction
)

-- Review sessions
reviews (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    word_id INTEGER REFERENCES words(id),
    sentence_id INTEGER REFERENCES sentences(id),
    quality INTEGER,  -- 0-5 or mapped from buttons
    reviewed_at TIMESTAMP
)
```

### Anki Import Strategy

**.apkg format**:
- SQLite database inside a ZIP file
- Main tables: `notes`, `cards`, `revlog`
- `notes.flds` contains fields separated by \x1f

**Import Process**:
1. Extract .apkg (rename to .zip, extract)
2. Open `collection.anki2` SQLite file
3. Parse notes table for vocabulary
4. Parse revlog for review history → calculate SM-2 state
5. Map to our schema

### Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11+ | User requirement, excellent ecosystem |
| Database | SQLite (dev) → PostgreSQL (prod) | Simple start, scale later |
| ORM | SQLAlchemy 2.0 | Modern async support, migrations |
| Web Framework | FastAPI | Modern, async, auto-docs, type hints |
| Frontend | HTMX + Jinja2 | Simple, progressive enhancement |
| AI | OpenAI API (GPT-4) | Best quality for sentence generation |
| Anki Parser | Custom + genanki lib | Handle .apkg format |

---

## Open Questions (Resolved)

1. ~~Word frequency corpus~~ → **User has existing corpus**
2. Sentence length optimization → **Start with 5-15 words, make configurable**
3. Multiple unknown words → **Start strict (1 only), allow "i+2" mode later**

## Next Steps

1. Set up Python project structure
2. Implement database models
3. Build Anki importer
4. Create SM-2 state calculator
5. Implement sentence generation with OpenAI
6. Build minimal web UI
