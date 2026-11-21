"""Tag a round as a hard input, for the per-tag accuracy in the eval.

    .venv/bin/python -m eval.tag_round <round_id> poker_face loud_room
    .venv/bin/python -m eval.tag_round --last poker_face

Tags we use: poker_face, loud_room, rehearsed_lie, crosstalk
"""

import argparse
import json

from server import db

KNOWN_TAGS = ["poker_face", "loud_room", "rehearsed_lie", "crosstalk"]


def main() -> None:
    argument_parser = argparse.ArgumentParser(description="Tag a round for the eval")
    argument_parser.add_argument("round_id", nargs="?", help="Round id (or use --last)")
    argument_parser.add_argument("tags", nargs="*", help=f"One or more of {KNOWN_TAGS}")
    argument_parser.add_argument("--last", action="store_true", help="Tag the most recent round")
    arguments = argument_parser.parse_args()

    db.create_tables()
    tags = arguments.tags
    if arguments.last:
        # With --last, the first word is a tag, not a round id.
        if arguments.round_id:
            tags = [arguments.round_id] + tags
        round_id = db.get_most_recent_round_id()
    else:
        round_id = arguments.round_id

    unknown_tags = [tag for tag in tags if tag not in KNOWN_TAGS]
    if unknown_tags:
        raise SystemExit(f"Unknown tags {unknown_tags}; use {KNOWN_TAGS}")
    if round_id is None or db.get_round(round_id) is None:
        raise SystemExit(f"No round with id {round_id}")

    db.save_round_tags(round_id, tags)
    print(f"Round {round_id} tagged {json.dumps(tags)}")


if __name__ == "__main__":
    main()
