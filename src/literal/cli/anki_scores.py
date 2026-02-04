#!/usr/bin/env python3
"""Query card scores from Anki via AnkiConnect API.

Requires:
- Anki running locally
- AnkiConnect addon installed (code: 2055492159)

Usage:
    ankiscore --list-decks
    ankiscore --deck "My Deck"
    ankiscore --deck "My Deck" --format json
    ankiscore --deck "My Deck" --format csv
    ankiscore --deck "My Deck" --status due
"""

import argparse
import json
import re
import sys
from datetime import datetime
from typing import Any

import httpx


class AnkiConnectError(Exception):
    """AnkiConnect API error."""

    pass


class AnkiConnect:
    """AnkiConnect API client."""

    QUEUE_NAMES = {
        -1: "suspended",
        0: "new",
        1: "learning",
        2: "review",
        3: "day-learn",
        4: "preview",
    }

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.url = f"http://{host}:{port}"
        self.client = httpx.Client(timeout=30.0)

    def request(self, action: str, **params: Any) -> Any:
        """Make AnkiConnect request."""
        payload: dict[str, Any] = {
            "action": action,
            "version": 6,
        }
        if params:
            payload["params"] = params

        try:
            response = self.client.post(self.url, json=payload)
            response.raise_for_status()
        except httpx.ConnectError:
            raise AnkiConnectError(
                "Cannot connect to Anki. Make sure Anki is running "
                "and AnkiConnect addon is installed."
            )
        except httpx.HTTPError as e:
            raise AnkiConnectError(f"HTTP error: {e}")

        result = response.json()

        if result.get("error"):
            raise AnkiConnectError(result["error"])

        return result.get("result")

    def get_deck_names(self) -> list[str]:
        """Get all deck names."""
        return self.request("deckNames")

    def get_cards_in_deck(self, deck_name: str) -> list[int]:
        """Get card IDs in a deck."""
        query = f'"deck:{deck_name}"'
        return self.request("findCards", query=query)

    def get_cards_info(self, card_ids: list[int]) -> list[dict[str, Any]]:
        """Get detailed card information."""
        if not card_ids:
            return []
        return self.request("cardsInfo", cards=card_ids)

    def get_deck_stats(self, deck_name: str) -> dict[str, Any]:
        """Get deck statistics."""
        decks = self.request("getDeckStats", decks=[deck_name])
        return decks.get(deck_name, {}) if decks else {}


def format_card_info(card: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant card information."""
    # Parse fields (front/back)
    fields = card.get("fields", {})
    front = ""
    back = ""

    # Try common field names
    for field_name in ["Front", "Word", "Expression", "Question"]:
        if field_name in fields:
            front = fields[field_name].get("value", "")
            break
    if not front and fields:
        front = list(fields.values())[0].get("value", "")

    for field_name in ["Back", "Translation", "Meaning", "Answer"]:
        if field_name in fields:
            back = fields[field_name].get("value", "")
            break
    if not back and len(fields) > 1:
        back = list(fields.values())[1].get("value", "")

    # Strip HTML
    front = re.sub(r"<[^>]+>", "", front).strip()
    back = re.sub(r"<[^>]+>", "", back).strip()

    # Calculate due date
    due = card.get("due", 0)
    queue = card.get("queue", 0)

    if queue == 0:  # New
        due_str = "new"
    elif queue == -1:  # Suspended
        due_str = "suspended"
    elif queue == 1:  # Learning
        due_str = "learning"
    else:
        # Due is days since collection creation or timestamp
        if due > 100000:  # Timestamp
            due_str = datetime.fromtimestamp(due).strftime("%Y-%m-%d")
        else:
            due_str = f"{due} days"

    return {
        "card_id": card.get("cardId"),
        "note_id": card.get("note"),
        "front": front[:50] + "..." if len(front) > 50 else front,
        "back": back[:50] + "..." if len(back) > 50 else back,
        "interval": card.get("interval", 0),
        "ease": card.get("factor", 0) / 10,  # Convert to percentage
        "reviews": card.get("reps", 0),
        "lapses": card.get("lapses", 0),
        "queue": AnkiConnect.QUEUE_NAMES.get(queue, str(queue)),
        "due": due_str,
        "due_raw": due,
        "queue_raw": queue,
    }


def group_cards_by_note(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group cards by note_id and average their scores."""
    notes: dict[int, list[dict[str, Any]]] = {}

    for card in cards:
        note_id = card["note_id"]
        if note_id not in notes:
            notes[note_id] = []
        notes[note_id].append(card)

    result = []
    for note_id, note_cards in notes.items():
        # Take front/back from first card (they're the same for all cards of a note)
        first = note_cards[0]

        # Average the scores across all cards
        avg_interval = sum(c["interval"] for c in note_cards) / len(note_cards)
        avg_ease = sum(c["ease"] for c in note_cards) / len(note_cards)
        total_reviews = sum(c["reviews"] for c in note_cards)
        total_lapses = sum(c["lapses"] for c in note_cards)

        # For status: use the "worst" status (most urgent)
        # Priority: new > learning > day-learn > review > suspended
        status_priority = {
            "new": 0,
            "learning": 1,
            "day-learn": 2,
            "review": 3,
            "suspended": 4,
            "preview": 5,
        }
        worst_status = min(note_cards, key=lambda c: status_priority.get(c["queue"], 99))

        # For due: use earliest due date
        earliest_due = min(note_cards, key=lambda c: (
            0 if c["queue_raw"] == 0 else  # new cards first
            1 if c["queue_raw"] == 1 else  # then learning
            c["due_raw"] if c["due_raw"] > 0 else 999999
        ))

        result.append({
            "note_id": note_id,
            "card_count": len(note_cards),
            "front": first["front"],
            "back": first["back"],
            "interval": round(avg_interval, 1),
            "ease": round(avg_ease, 1),
            "reviews": total_reviews,
            "lapses": total_lapses,
            "queue": worst_status["queue"],
            "due": earliest_due["due"],
        })

    return result


def print_table(notes: list[dict[str, Any]]) -> None:
    """Print notes as ASCII table."""
    if not notes:
        print("No notes found.")
        return

    # Column widths
    headers = ["Front", "Back", "Interval", "Ease%", "Reviews", "Lapses", "Status", "Due"]
    widths = [20, 20, 8, 6, 7, 6, 10, 12]

    # Header
    header_row = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    separator = "-+-".join("-" * w for w in widths)

    print(header_row)
    print(separator)

    # Rows
    for note in notes:
        interval = note["interval"]
        interval_str = f"{interval:.1f}" if isinstance(interval, float) else str(interval)
        row = [
            str(note["front"])[:20].ljust(20),
            str(note["back"])[:20].ljust(20),
            interval_str.rjust(8),
            f"{note['ease']:.0f}".rjust(6),
            str(note["reviews"]).rjust(7),
            str(note["lapses"]).rjust(6),
            str(note["queue"]).ljust(10),
            str(note["due"]).ljust(12),
        ]
        print(" | ".join(row))

    print(separator)
    print(f"Total: {len(notes)} notes")


def print_json(cards: list[dict[str, Any]]) -> None:
    """Print cards as JSON."""
    print(json.dumps(cards, indent=2, ensure_ascii=False))


def print_csv(notes: list[dict[str, Any]]) -> None:
    """Print notes as CSV."""
    if not notes:
        return

    headers = ["note_id", "front", "back", "interval", "ease", "reviews", "lapses", "queue", "due"]
    print(",".join(headers))

    for note in notes:
        row = [
            str(note["note_id"]),
            f'"{note["front"]}"',
            f'"{note["back"]}"',
            str(note["interval"]),
            f'{note["ease"]:.0f}',
            str(note["reviews"]),
            str(note["lapses"]),
            str(note["queue"]),
            str(note["due"]),
        ]
        print(",".join(row))


def main() -> None:
    """Main entry point for ankiscore CLI."""
    parser = argparse.ArgumentParser(
        prog="ankiscore",
        description="Query card scores from Anki via AnkiConnect",
    )
    parser.add_argument(
        "--list-decks",
        action="store_true",
        help="List all available decks",
    )
    parser.add_argument(
        "--deck",
        "-d",
        type=str,
        help="Deck name to query",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--status",
        "-s",
        choices=["all", "new", "learning", "review", "due", "suspended"],
        default="all",
        help="Filter by card status",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="AnkiConnect host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="AnkiConnect port (default: 8765)",
    )

    args = parser.parse_args()

    if not args.list_decks and not args.deck:
        parser.print_help()
        sys.exit(1)

    try:
        anki = AnkiConnect(host=args.host, port=args.port)

        if args.list_decks:
            decks = anki.get_deck_names()
            print("Available decks:")
            for deck in sorted(decks):
                print(f"  - {deck}")
            return

        # Get cards in deck
        card_ids = anki.get_cards_in_deck(args.deck)

        if not card_ids:
            print(f"No cards found in deck: {args.deck}")
            return

        # Get card info
        cards_raw = anki.get_cards_info(card_ids)
        cards = [format_card_info(c) for c in cards_raw]

        # Group by note (average scores across cards)
        notes = group_cards_by_note(cards)

        # Filter by status
        if args.status != "all":
            if args.status == "due":
                notes = [n for n in notes if n["queue"] in ("review", "day-learn")]
            else:
                notes = [n for n in notes if n["queue"] == args.status]

        # Sort by interval (highest first)
        notes.sort(key=lambda n: n["interval"], reverse=True)

        # Output
        if args.format == "json":
            print_json(notes)
        elif args.format == "csv":
            print_csv(notes)
        else:
            print_table(notes)

    except AnkiConnectError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
