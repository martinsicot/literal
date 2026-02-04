#!/usr/bin/env python3
"""Main CLI for Literal - Basque i+1 sentence learning system.

Usage:
    literal seed                        # Initialize database with cases and default user
    literal import-vocab <csv_path>     # Import vocabulary from CSV
    literal sync-lemmas <deck_name>     # Sync lemma progress from Anki
    literal sync-sentences <deck_name>  # Sync sentence progress from Anki
    literal generate [--count N]        # Generate sentences
    literal stats                       # Show progress overview
    literal unlock-level N              # Manually unlock case level
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

from literal.config import get_settings
from literal.models import (
    GrammaticalCase,
    Sentence,
    User,
    UserCaseProgress,
    Word,
)
from literal.models.base import get_session_factory
from literal.services import (
    AnkiConnectError,
    AnkiSync,
    CSVImporter,
    seed_all,
    seed_grammatical_cases,
    seed_user_case_progress,
)


async def cmd_seed(args: argparse.Namespace) -> int:
    """Initialize database with grammatical cases and default user."""
    async with get_session_factory()() as session:
        results = await seed_all(session)

        if results["cases"] > 0:
            print(f"Seeded {results['cases']} grammatical cases")
        else:
            print("Grammatical cases already seeded")

        print(f"Default user ID: {results['user_id']}")

        if results["progress"] > 0:
            print(f"Initialized {results['progress']} case progress records")
        else:
            print("Case progress already initialized")

    return 0


async def cmd_import_vocab(args: argparse.Namespace) -> int:
    """Import vocabulary from CSV file."""
    csv_path = Path(args.csv_path)

    if not csv_path.exists():
        print(f"Error: File not found: {csv_path}", file=sys.stderr)
        return 1

    async with get_session_factory()() as session:
        # Get or create user
        user_id = args.user_id
        if user_id is None:
            # Find default user
            result = await session.execute(
                select(User).where(User.username == "default")
            )
            user = result.scalar_one_or_none()
            if user is None:
                print("Error: No default user. Run 'literal seed' first.", file=sys.stderr)
                return 1
            user_id = user.id

        # Import
        importer = CSVImporter(session)
        result = await importer.import_vocabulary(
            csv_path,
            user_id,
            delimiter=args.delimiter,
        )

        print(f"Import complete: {result}")

        if result.errors:
            print("\nErrors:")
            for error in result.errors[:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(result.errors) > 10:
                print(f"  ... and {len(result.errors) - 10} more errors")

    return 0 if not result.errors else 1


async def cmd_sync_lemmas(args: argparse.Namespace) -> int:
    """Sync lemma progress from Anki."""
    async with get_session_factory()() as session:
        # Get user
        user_id = args.user_id
        if user_id is None:
            result = await session.execute(
                select(User).where(User.username == "default")
            )
            user = result.scalar_one_or_none()
            if user is None:
                print("Error: No default user. Run 'literal seed' first.", file=sys.stderr)
                return 1
            user_id = user.id

        try:
            sync = AnkiSync(session, host=args.host, port=args.port)
            result = await sync.sync_lemma_progress(
                args.deck_name,
                user_id,
                known_threshold_days=args.threshold,
            )
            await sync.close()

            print(f"Sync complete: {result}")

            if result.newly_known > 0:
                print(f"\n{result.newly_known} words newly marked as 'known'!")

        except AnkiConnectError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    return 0


async def cmd_sync_sentences(args: argparse.Namespace) -> int:
    """Sync sentence progress from Anki."""
    async with get_session_factory()() as session:
        # Get user
        user_id = args.user_id
        if user_id is None:
            result = await session.execute(
                select(User).where(User.username == "default")
            )
            user = result.scalar_one_or_none()
            if user is None:
                print("Error: No default user. Run 'literal seed' first.", file=sys.stderr)
                return 1
            user_id = user.id

        try:
            sync = AnkiSync(session, host=args.host, port=args.port)
            result = await sync.sync_sentence_progress(args.deck_name, user_id)
            await sync.close()

            print(f"Sync complete: {result}")

        except AnkiConnectError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    return 0


async def cmd_sync_known_decks(args: argparse.Namespace) -> int:
    """Sync known words from additional Anki decks by matching Basque lemmas."""
    from datetime import UTC, datetime
    import httpx

    async with get_session_factory()() as session:
        # Query Anki for cards from specified decks
        deck_queries = [f'deck:"{deck}"' for deck in args.decks]
        query = " OR ".join(deck_queries)

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Find cards
            response = await client.post(
                f"http://{args.host}:{args.port}",
                json={"action": "findCards", "version": 6, "params": {"query": query}},
            )
            result = response.json()
            if result.get("error"):
                print(f"Error querying Anki: {result['error']}", file=sys.stderr)
                return 1

            card_ids = result["result"]
            print(f"Found {len(card_ids)} cards from decks: {', '.join(args.decks)}")

            if not card_ids:
                print("No cards found in specified decks")
                return 0

            # Get card info
            response = await client.post(
                f"http://{args.host}:{args.port}",
                json={"action": "cardsInfo", "version": 6, "params": {"cards": card_ids}},
            )
            result = response.json()
            if result.get("error"):
                print(f"Error getting card info: {result['error']}", file=sys.stderr)
                return 1

            cards_info = result["result"]

        # Extract unique words with their best interval
        # Support both "Euskera" and "Basque" field names
        words_data: dict[str, dict] = {}  # basque_lemma -> {interval, french, deck}

        for card in cards_info:
            fields = card.get("fields", {})
            # Try different field names for Basque
            basque = (
                fields.get("Euskera", {}).get("value", "").strip()
                or fields.get("Basque", {}).get("value", "").strip()
                or fields.get("basque", {}).get("value", "").strip()
            )
            french = (
                fields.get("Francais", {}).get("value", "").strip()
                or fields.get("French", {}).get("value", "").strip()
                or fields.get("front", {}).get("value", "").strip()
            )
            interval = card.get("interval", 0)
            deck = card.get("deckName", "").split("::")[0]

            if basque:
                # Keep the one with highest interval
                if basque not in words_data or interval > words_data[basque]["interval"]:
                    words_data[basque] = {
                        "interval": interval,
                        "french": french,
                        "deck": deck,
                    }

        print(f"Unique Basque words extracted: {len(words_data)}")
        print(f"Words with interval >= {args.threshold} days: {sum(1 for w in words_data.values() if w['interval'] >= args.threshold)}")

        # Match against database and update
        basque_lemmas = list(words_data.keys())
        db_words = await session.execute(
            select(Word).where(Word.basque_lemma.in_(basque_lemmas))
        )
        db_words_list = db_words.scalars().all()

        print(f"Matching words in database: {len(db_words_list)}")

        updated = 0
        newly_known = 0

        for word in db_words_list:
            anki_data = words_data.get(word.basque_lemma)
            if anki_data:
                # Update interval if Anki has higher value
                if anki_data["interval"] > word.anki_interval:
                    word.anki_interval = anki_data["interval"]
                    word.last_synced = datetime.now(UTC)
                    updated += 1

                    # Check if now known
                    if anki_data["interval"] >= args.threshold and not word.is_known:
                        word.is_known = True
                        newly_known += 1

        await session.commit()

        print(f"\nSync complete:")
        print(f"  - Words updated: {updated}")
        print(f"  - Newly marked as known: {newly_known}")

    return 0


async def cmd_push_to_anki(args: argparse.Namespace) -> int:
    """Push existing sentences to Anki that haven't been uploaded yet."""
    from collections import defaultdict

    from sqlalchemy.orm import selectinload

    from literal.services.anki_sync import AnkiConnectError, AnkiSync

    # Level names for sub-deck organization
    LEVEL_NAMES = {
        1: "Level 1 - Core",
        2: "Level 2 - Location",
        3: "Level 3 - Relation",
        4: "Level 4 - Advanced",
    }

    async with get_session_factory()() as session:
        # Get user
        user_id = args.user_id
        if user_id is None:
            result = await session.execute(
                select(User).where(User.username == "default")
            )
            user = result.scalar_one_or_none()
            if user is None:
                print("Error: No default user. Run 'literal seed' first.", file=sys.stderr)
                return 1
            user_id = user.id

        # Find sentences without anki_note_id, with case info loaded
        sentences_result = await session.execute(
            select(Sentence)
            .options(selectinload(Sentence.target_case))
            .where(
                Sentence.user_id == user_id,
                Sentence.anki_note_id == None,  # noqa: E711
            )
        )
        sentences = sentences_result.scalars().all()

        if not sentences:
            print("No sentences to push - all sentences already in Anki.")
            return 0

        # Group sentences by level
        sentences_by_level: dict[int, list] = defaultdict(list)
        for sentence in sentences:
            level = sentence.target_case.level if sentence.target_case else 1
            sentences_by_level[level].append(sentence)

        print(f"Found {len(sentences)} sentences to push to Anki...")
        for level in sorted(sentences_by_level.keys()):
            print(f"  {LEVEL_NAMES.get(level, f'Level {level}')}: {len(sentences_by_level[level])} sentences")

        try:
            anki_sync = AnkiSync(session)

            pushed = 0
            for level in sorted(sentences_by_level.keys()):
                level_sentences = sentences_by_level[level]
                level_name = LEVEL_NAMES.get(level, f"Level {level}")
                deck_name = f"{args.deck}::{level_name}"

                # Ensure sub-deck exists
                await anki_sync.ensure_deck(deck_name)
                print(f"\n→ Pushing to '{deck_name}':")

                for sentence in level_sentences:
                    try:
                        note_id = await anki_sync.create_sentence_card(
                            sentence=sentence,
                            deck_name=deck_name,
                        )
                        pushed += 1
                        case_name = sentence.target_case.name if sentence.target_case else "?"
                        print(f"  [{pushed}] [{case_name}] {sentence.sentence_text[:40]}... → Note {note_id}")
                    except AnkiConnectError as e:
                        print(f"  Error: {e}", file=sys.stderr)

            await anki_sync.close()
            print(f"\n✓ Pushed {pushed}/{len(sentences)} sentences to '{args.deck}'")

        except AnkiConnectError as e:
            print(f"Error connecting to Anki: {e}", file=sys.stderr)
            return 1

    return 0


async def cmd_stats(args: argparse.Namespace) -> int:
    """Show progress overview."""
    async with get_session_factory()() as session:
        # Get user
        user_id = args.user_id
        if user_id is None:
            result = await session.execute(
                select(User).where(User.username == "default")
            )
            user = result.scalar_one_or_none()
            if user is None:
                print("Error: No default user. Run 'literal seed' first.", file=sys.stderr)
                return 1
            user_id = user.id

        print("=" * 50)
        print("LITERAL PROGRESS OVERVIEW")
        print("=" * 50)

        # Vocabulary stats
        total_words = await session.scalar(select(func.count(Word.id)))
        known_words = await session.scalar(
            select(func.count(Word.id)).where(Word.is_known == True)  # noqa: E712
        )
        print(f"\nVocabulary: {total_words} words imported, {known_words} known")

        # Words with usage
        words_with_usage = await session.scalar(
            select(func.count(Word.id)).where(Word.usage_count >= 3)
        )
        words_partial_usage = await session.scalar(
            select(func.count(Word.id)).where(
                Word.usage_count > 0, Word.usage_count < 3
            )
        )
        unused_known = await session.scalar(
            select(func.count(Word.id)).where(
                Word.is_known == True, Word.usage_count == 0  # noqa: E712
            )
        )
        print(f"  - Words used in 3+ sentences: {words_with_usage}")
        print(f"  - Words used in 1-2 sentences: {words_partial_usage}")
        print(f"  - Known words not yet used: {unused_known}")

        # Case progress
        print("\nCase Progress:")

        # Get all cases ordered by level
        cases_result = await session.execute(
            select(GrammaticalCase).order_by(GrammaticalCase.level, GrammaticalCase.id)
        )
        cases = cases_result.scalars().all()

        current_level = 0
        level_names = {1: "Core", 2: "Location", 3: "Relation", 4: "Advanced"}

        for case in cases:
            if case.level != current_level:
                current_level = case.level
                print(f"\n  Level {current_level} ({level_names.get(current_level, 'Unknown')}):")

            # Get user progress for this case
            progress_result = await session.execute(
                select(UserCaseProgress).where(
                    UserCaseProgress.user_id == user_id,
                    UserCaseProgress.case_id == case.id,
                )
            )
            progress = progress_result.scalar_one_or_none()

            if progress:
                status = "✓" if progress.is_mastered else ""
                locked = "" if progress.unlocked else " [LOCKED]"
                print(
                    f"    - {case.name.capitalize():12} {progress.sentences_generated:3}/30 sentences, "
                    f"avg interval {progress.avg_interval:5.1f} days {status}{locked}"
                )
            else:
                print(f"    - {case.name.capitalize():12} No progress data")

        # Total sentences
        total_sentences = await session.scalar(
            select(func.count(Sentence.id)).where(Sentence.user_id == user_id)
        )
        in_anki = await session.scalar(
            select(func.count(Sentence.id)).where(
                Sentence.user_id == user_id,
                Sentence.anki_note_id != None,  # noqa: E711
            )
        )
        print(f"\nTotal sentences: {total_sentences} ({in_anki} in Anki)")

        print("=" * 50)

    return 0


async def cmd_unlock_level(args: argparse.Namespace) -> int:
    """Manually unlock a case level."""
    async with get_session_factory()() as session:
        # Get user
        user_id = args.user_id
        if user_id is None:
            result = await session.execute(
                select(User).where(User.username == "default")
            )
            user = result.scalar_one_or_none()
            if user is None:
                print("Error: No default user. Run 'literal seed' first.", file=sys.stderr)
                return 1
            user_id = user.id

        # Get cases at specified level
        cases_result = await session.execute(
            select(GrammaticalCase).where(GrammaticalCase.level == args.level)
        )
        cases = cases_result.scalars().all()

        if not cases:
            print(f"Error: No cases found at level {args.level}", file=sys.stderr)
            return 1

        # Unlock progress records
        unlocked = 0
        for case in cases:
            progress_result = await session.execute(
                select(UserCaseProgress).where(
                    UserCaseProgress.user_id == user_id,
                    UserCaseProgress.case_id == case.id,
                )
            )
            progress = progress_result.scalar_one_or_none()

            if progress and not progress.unlocked:
                progress.unlocked = True
                unlocked += 1

        await session.commit()
        print(f"Unlocked {unlocked} cases at level {args.level}")

    return 0


async def cmd_generate(args: argparse.Namespace) -> int:
    """Generate sentences with case-aware Basque grammar."""
    async with get_session_factory()() as session:
        # Get user
        user_id = args.user_id
        if user_id is None:
            result = await session.execute(
                select(User).where(User.username == "default")
            )
            user = result.scalar_one_or_none()
            if user is None:
                print("Error: No default user. Run 'literal seed' first.", file=sys.stderr)
                return 1
            user_id = user.id

        # Import services here to avoid circular imports
        from literal.services.anki_sync import AnkiConnectError, AnkiSync
        from literal.services.generator import SentenceGenerator
        from literal.services.progression import ProgressionService
        from literal.services.tts import MockTTSService, TTSService

        # Initialize services
        progression = ProgressionService(session)
        generator = SentenceGenerator(session)

        # Try to use real TTS, fall back to mock
        try:
            tts: TTSService | MockTTSService = TTSService()
        except Exception:
            print("Note: Using mock TTS (Google Cloud TTS not configured)")
            tts = MockTTSService()

        # Initialize AnkiSync if pushing to Anki
        anki_sync = None
        if args.push_to_anki:
            anki_sync = AnkiSync(session)
            try:
                # Verify Anki connection and ensure deck exists
                await anki_sync.ensure_deck(args.deck)
                print(f"Will push to Anki deck: {args.deck}")
            except AnkiConnectError as e:
                print(f"Warning: Cannot connect to Anki: {e}", file=sys.stderr)
                print("Sentences will be generated but NOT pushed to Anki.", file=sys.stderr)
                anki_sync = None

        # Check for known words
        known_count = await progression.get_known_word_count()
        if known_count == 0:
            print("Error: No known words. Sync your Anki progress first:", file=sys.stderr)
            print("  literal sync-lemmas <deck_name>", file=sys.stderr)
            return 1

        # Determine case and number to practice
        if args.case:
            # User specified a case
            case_result = await session.execute(
                select(GrammaticalCase).where(GrammaticalCase.name == args.case.lower())
            )
            target_case = case_result.scalar_one_or_none()
            if target_case is None:
                print(f"Error: Unknown case '{args.case}'", file=sys.stderr)
                print("Available cases: absolutive, ergative, dative, inessive, "
                      "adlative, ablative, genitive, comitative, benefactive, "
                      "instrumental, motivative, prolative, partitive", file=sys.stderr)
                return 1

            target_number = args.number or "singular"
        else:
            # Auto-select next case to practice
            case_and_number = await progression.get_next_case_to_practice(user_id)
            if case_and_number is None:
                print("Error: No cases available to practice", file=sys.stderr)
                print("All cases at current level may be complete.", file=sys.stderr)
                return 1

            target_case, target_number = case_and_number

        print(f"Generating {args.count} sentence(s) for {target_case.name} ({target_number})...")
        print(f"Known words available: {known_count}")
        print()

        generated = 0
        for i in range(args.count):
            sentence = await generator.generate_and_save_for_case(
                user_id=user_id,
                target_case=target_case,
                target_number=target_number,
                progression_service=progression,
                tts_service=tts,
            )

            if sentence:
                generated += 1
                print(f"[{generated}] {sentence.sentence_text}")
                print(f"    FR: {sentence.french_text}")
                if sentence.target_form:
                    print(f"    Target form: {sentence.target_form}")

                # Push to Anki if enabled
                if anki_sync:
                    try:
                        note_id = await anki_sync.create_sentence_card(
                            sentence=sentence,
                            deck_name=args.deck,
                        )
                        print(f"    Anki: Created note {note_id}")
                    except AnkiConnectError as e:
                        print(f"    Anki: Failed to create card: {e}", file=sys.stderr)

                print()
            else:
                print(f"Failed to generate sentence {i + 1}", file=sys.stderr)

        print(f"Generated {generated}/{args.count} sentences")
        if anki_sync:
            if generated > 0:
                print(f"Pushed {generated} cards to Anki deck '{args.deck}'")
            await anki_sync.close()

        # Check if level should unlock
        new_level = await progression.check_level_unlock(user_id)
        if new_level:
            print(f"\nCongratulations! Level {new_level} unlocked!")

    return 0 if generated > 0 else 1


def main() -> None:
    """Main entry point for literal CLI."""
    parser = argparse.ArgumentParser(
        prog="literal",
        description="Basque i+1 sentence learning system",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # seed command
    seed_parser = subparsers.add_parser("seed", help="Initialize database")
    seed_parser.set_defaults(func=cmd_seed)

    # import-vocab command
    import_parser = subparsers.add_parser("import-vocab", help="Import vocabulary from CSV")
    import_parser.add_argument("csv_path", help="Path to CSV file")
    import_parser.add_argument("--user-id", type=int, help="User ID (default: default user)")
    import_parser.add_argument(
        "--delimiter", default="\t", help="CSV delimiter (default: tab)"
    )
    import_parser.set_defaults(func=cmd_import_vocab)

    # sync-lemmas command
    sync_lemmas_parser = subparsers.add_parser(
        "sync-lemmas", help="Sync lemma progress from Anki"
    )
    sync_lemmas_parser.add_argument("deck_name", help="Anki deck name")
    sync_lemmas_parser.add_argument("--user-id", type=int, help="User ID")
    sync_lemmas_parser.add_argument("--host", default="localhost", help="AnkiConnect host")
    sync_lemmas_parser.add_argument("--port", type=int, default=8765, help="AnkiConnect port")
    sync_lemmas_parser.add_argument(
        "--threshold", type=int, default=14, help="Days interval for 'known' status"
    )
    sync_lemmas_parser.set_defaults(func=cmd_sync_lemmas)

    # sync-sentences command
    sync_sentences_parser = subparsers.add_parser(
        "sync-sentences", help="Sync sentence progress from Anki"
    )
    sync_sentences_parser.add_argument("deck_name", help="Anki deck name")
    sync_sentences_parser.add_argument("--user-id", type=int, help="User ID")
    sync_sentences_parser.add_argument("--host", default="localhost", help="AnkiConnect host")
    sync_sentences_parser.add_argument("--port", type=int, default=8765, help="AnkiConnect port")
    sync_sentences_parser.set_defaults(func=cmd_sync_sentences)

    # sync-known-decks command
    sync_known_parser = subparsers.add_parser(
        "sync-known-decks",
        help="Sync known words from other Anki decks by Basque lemma matching"
    )
    sync_known_parser.add_argument(
        "decks", nargs="+",
        help="Anki deck names to sync from (e.g., 'Vocabulaire Basic' 'Bakarka')"
    )
    sync_known_parser.add_argument("--host", default="localhost", help="AnkiConnect host")
    sync_known_parser.add_argument("--port", type=int, default=8765, help="AnkiConnect port")
    sync_known_parser.add_argument(
        "--threshold", type=int, default=14,
        help="Days interval for 'known' status (default: 14)"
    )
    sync_known_parser.set_defaults(func=cmd_sync_known_decks)

    # push-to-anki command
    push_parser = subparsers.add_parser(
        "push-to-anki",
        help="Push existing sentences to Anki that haven't been uploaded yet"
    )
    push_parser.add_argument(
        "--deck", default="Basque::Sentences",
        help="Anki deck name (default: Basque::Sentences)"
    )
    push_parser.add_argument("--user-id", type=int, help="User ID")
    push_parser.set_defaults(func=cmd_push_to_anki)

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show progress overview")
    stats_parser.add_argument("--user-id", type=int, help="User ID")
    stats_parser.set_defaults(func=cmd_stats)

    # unlock-level command
    unlock_parser = subparsers.add_parser("unlock-level", help="Manually unlock case level")
    unlock_parser.add_argument("level", type=int, choices=[1, 2, 3, 4], help="Level to unlock")
    unlock_parser.add_argument("--user-id", type=int, help="User ID")
    unlock_parser.set_defaults(func=cmd_unlock_level)

    # generate command
    generate_parser = subparsers.add_parser("generate", help="Generate sentences")
    generate_parser.add_argument("--count", type=int, default=1, help="Number of sentences")
    generate_parser.add_argument("--case", help="Specific case to practice")
    generate_parser.add_argument(
        "--number", choices=["singular", "plural"], help="Grammatical number"
    )
    generate_parser.add_argument("--user-id", type=int, help="User ID")
    generate_parser.add_argument(
        "--push-to-anki", action="store_true",
        help="Push generated sentences to Anki deck"
    )
    generate_parser.add_argument(
        "--deck", default="Basque::Sentences",
        help="Anki deck name for generated sentences (default: Basque::Sentences)"
    )
    generate_parser.set_defaults(func=cmd_generate)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Run the async command
    result = asyncio.run(args.func(args))
    sys.exit(result)


if __name__ == "__main__":
    main()
