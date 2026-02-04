# Literal - Basque i+1 Sentence Learning System

A CLI tool for learning Basque through comprehensible input (i+1 methodology). Generates sentences using words you already know, with proper Basque grammatical cases, and syncs with Anki for spaced repetition.

## Prerequisites

- **Anki** with [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on installed
- **Python 3.11+** with pipenv
- **OpenAI API key** for sentence generation
- **Google Cloud API key** (optional, for TTS audio)

## Installation

```bash
cd literal
pipenv install
pipenv shell
```

## Configuration

Create a `.env.local` file with your API keys:

```bash
# Required for sentence generation
OPENAI_API_KEY=sk-your-key-here

# Optional: for TTS audio generation
GOOGLE_CLOUD_API_KEY=your-google-cloud-api-key

# Optional settings
DATABASE_URL=sqlite+aiosqlite:///./literal.db
DEBUG=true
SQL_ECHO=false
```

## Quick Start

```bash
# 1. Initialize the database
literal seed

# 2. Import your vocabulary CSV
literal import-vocab data/vocabulary.csv

# 3. Sync your known words from Anki
literal sync-lemmas "vocab_3_ans"

# 4. (Optional) Sync from additional decks you already know
literal sync-known-decks "Vocabulaire Basic" "Bakarra"

# 5. Generate sentences and push to Anki
literal generate --count 5 --push-to-anki

# 6. Check your progress
literal stats
```

## Commands

### `literal seed`

Initialize the database with grammatical cases and default user.

```bash
literal seed
```

Creates:
- 13 Basque grammatical cases (4 levels)
- Default user with case progress records
- Level 1 cases unlocked by default (absolutive, ergative, dative)

---

### `literal import-vocab <csv_path>`

Import vocabulary from a CSV file.

```bash
literal import-vocab data/vocabulary.csv
literal import-vocab data/vocabulary.csv --delimiter ","
literal import-vocab data/vocabulary.csv --user-id 2
```

**Options:**
- `--delimiter` - CSV delimiter (default: tab `\t`)
- `--user-id` - User ID (default: default user)

**CSV Format (tab-separated):**
```
index	mot	frequence	LEMMA	Anki Card ID	Categorie Grammaticale
1	dans	5000	barru	1234567890	preposition
2	maison	4500	etxe	1234567891	noun
```

Required columns: `mot` (French), `LEMMA` (Basque), `frequence`
Optional columns: `Anki Card ID`, `Categorie Grammaticale`

---

### `literal sync-lemmas <deck_name>`

Sync learning progress from your main Anki vocabulary deck. Updates word intervals and marks words as "known" when they reach the threshold.

```bash
literal sync-lemmas "vocab_3_ans"
literal sync-lemmas "Basque::Vocabulary" --threshold 21
literal sync-lemmas "My Deck" --host localhost --port 8765
```

**Options:**
- `--threshold` - Days interval to mark as "known" (default: 14)
- `--host` - AnkiConnect host (default: localhost)
- `--port` - AnkiConnect port (default: 8765)
- `--user-id` - User ID

**Requirements:**
- Anki must be running with AnkiConnect
- Cards must have `anki_note_id` matching the imported vocabulary

---

### `literal sync-known-decks <deck1> [deck2] ...`

Sync known words from other Anki decks by matching Basque lemmas. Useful when you have words in multiple decks that overlap with your vocabulary database.

```bash
literal sync-known-decks "Vocabulaire Basic" "Bakarka"
literal sync-known-decks "Old Deck" --threshold 7
```

**Options:**
- `--threshold` - Days interval for "known" status (default: 14)
- `--host` - AnkiConnect host
- `--port` - AnkiConnect port

**How it works:**
1. Queries all cards from specified decks
2. Extracts Basque words (looks for "Euskera", "Basque", or "basque" fields)
3. Matches by basque_lemma to words in your database
4. Updates intervals (keeps the highest)
5. Marks words as known if interval >= threshold

---

### `literal sync-sentences <deck_name>`

Sync review progress for generated sentences back from Anki. Updates sentence intervals and case progress statistics.

```bash
literal sync-sentences "Basque::Sentences"
```

**Options:**
- `--host` - AnkiConnect host
- `--port` - AnkiConnect port
- `--user-id` - User ID

---

### `literal generate`

Generate i+1 sentences using known words with proper Basque grammatical cases.

```bash
# Generate 1 sentence (auto-selects case)
literal generate

# Generate 5 sentences
literal generate --count 5

# Generate and push directly to Anki
literal generate --count 3 --push-to-anki

# Generate for a specific case
literal generate --case ergative --number singular

# Generate for plural forms
literal generate --case absolutive --number plural

# Use a custom Anki deck
literal generate --push-to-anki --deck "My Custom Deck"
```

**Options:**
- `--count N` - Number of sentences to generate (default: 1)
- `--case` - Specific grammatical case to practice
- `--number` - `singular` or `plural` (default: auto-select)
- `--push-to-anki` - Push generated cards to Anki
- `--deck` - Anki deck name (default: "Basque::Sentences")
- `--user-id` - User ID

**Available cases:**
| Level | Cases |
|-------|-------|
| 1 (Core) | absolutive, ergative, dative |
| 2 (Location) | inessive, adlative, ablative |
| 3 (Relation) | genitive, comitative, benefactive |
| 4 (Advanced) | instrumental, motivative, prolative, partitive |

**Level 1 Progression (Sequential Mastery):**
- Start with **absolutive** only
- **Ergative** unlocks when 50% of absolutive sentences have good Anki intervals (14+ days)
- **Dative** unlocks when 50% of ergative sentences have good intervals
- Continue building earlier cases even after introducing new ones

**What it generates:**
- Basque sentence with target word in specified case
- French translation
- TTS audio for both languages (if Google Cloud configured)
- Anki card (if `--push-to-anki` enabled)

---

### `literal push-to-anki`

Push existing sentences to Anki that haven't been uploaded yet.

```bash
literal push-to-anki
literal push-to-anki --deck "Custom::Deck"
```

**Options:**
- `--deck` - Anki deck name (default: "Basque::Sentences")
- `--user-id` - User ID

Useful when you generated sentences without `--push-to-anki` and want to upload them later.

---

### `literal stats`

Show your learning progress overview.

```bash
literal stats
literal stats --user-id 2
```

**Output example:**
```
==================================================
LITERAL PROGRESS OVERVIEW
==================================================

Vocabulary: 2420 words imported, 75 known
  - Words used in 3+ sentences: 0
  - Words used in 1-2 sentences: 9
  - Known words not yet used: 66

Case Progress:

  Level 1 (Core):
    - Absolutive     3/30 sentences, avg interval   0.0 days
    - Ergative       1/30 sentences, avg interval   0.0 days
    - Dative         0/30 sentences, avg interval   0.0 days

  Level 2 (Location): [LOCKED]
    - Inessive       0/30 sentences, avg interval   0.0 days  [LOCKED]
    - Adlative       0/30 sentences, avg interval   0.0 days  [LOCKED]
    - Ablative       0/30 sentences, avg interval   0.0 days  [LOCKED]

Total sentences: 4 (4 in Anki)
==================================================
```

---

### `literal unlock-level <level>`

Manually unlock a case level (1-4).

```bash
literal unlock-level 2
literal unlock-level 3 --user-id 2
```

**Levels:**
- 1 (Core): absolutive, ergative, dative - unlocked by default
- 2 (Location): inessive, adlative, ablative
- 3 (Relation): genitive, comitative, benefactive
- 4 (Advanced): instrumental, motivative, prolative, partitive

Normally levels unlock automatically when you master the previous level's cases.

---

## Typical Workflow

### Initial Setup

```bash
# Initialize
literal seed
literal import-vocab data/vocabulary.csv

# Sync your known words
literal sync-lemmas "vocab_3_ans"
literal sync-known-decks "Other Deck 1" "Other Deck 2"

# Check status
literal stats
```

### Daily Practice

```bash
# Generate new sentences
literal generate --count 5 --push-to-anki

# Review in Anki...

# Sync progress back
literal sync-sentences "Basque::Sentences"

# Check progress
literal stats
```

### Progression

**Level 1 (Sequential Mastery):**
1. Start with **absolutive** case only
2. Generate sentences and review in Anki
3. When 50% of absolutive sentences have 14+ day intervals, **ergative** unlocks
4. When 50% of ergative sentences have 14+ day intervals, **dative** unlocks
5. Continue building all active cases until each reaches 30 sentences
6. When all 3 cases have 30 sentences with good intervals, Level 2 unlocks

**Levels 2-4:**
- Balance across all available cases at that level
- Same progression: 30 sentences per case, then next level unlocks

---

## Anki Card Format

**Front:**
- French sentence (text)
- French audio (if TTS configured)

**Back:**
- Basque sentence (text)
- Basque audio (if TTS configured)

---

## Troubleshooting

### "No known words" error
```bash
# Make sure you've synced from Anki
literal sync-lemmas "your-deck-name"

# Or sync from other decks
literal sync-known-decks "Other Deck"
```

### AnkiConnect errors
- Ensure Anki is running
- Ensure AnkiConnect add-on is installed
- Check the port (default: 8765)

### TTS not working
- Set `GOOGLE_CLOUD_API_KEY` in `.env.local`
- The system falls back to mock TTS if not configured (empty audio files)

### OpenAI errors
- Verify your API key in `.env.local`
- Check your OpenAI account has credits

---

## Database

SQLite database stored at `./literal.db` (configurable via `DATABASE_URL`).

To reset everything:
```bash
rm literal.db
literal seed
literal import-vocab data/vocabulary.csv
```

---

## Architecture

```
CSV Vocabulary
     ↓ import-vocab
Literal DB ←── sync-lemmas ←── Anki (vocabulary deck)
     ↓
Word becomes "known" (interval >= 14 days)
     ↓
Generate sentence (known word in target case)
     ↓
TTS audio (French + Basque)
     ↓
Push to Anki ──→ Anki (sentence deck)
     ↓
sync-sentences ←── Review progress
     ↓
Level progression (unlock new cases)
```
