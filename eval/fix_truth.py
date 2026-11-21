"""Fix which statement was really the lie in a past round, then re-score it.

    .venv/bin/python -m eval.fix_truth <round_id> <statement 1-3>

Use this when a player lied on a different statement than the secret one.
"""

import argparse

from server import db
from server.scoring import score_round_result


def main() -> None:
    argument_parser = argparse.ArgumentParser(description="Correct the true lie of a past round")
    argument_parser.add_argument("round_id")
    argument_parser.add_argument("statement", type=int, choices=[1, 2, 3])
    arguments = argument_parser.parse_args()

    db.create_tables()
    round_info = db.get_round(arguments.round_id)
    if round_info is None:
        raise SystemExit(f"No round with id {arguments.round_id}")

    old_result = round_info["result"]
    db.save_confirmed_lie(arguments.round_id, arguments.statement)
    new_result = score_round_result(arguments.round_id, arguments.statement, "corrected_after")

    old_text = f"lie {old_result.get('lie_statement', old_result['lie_index'] + 1)}, correct={old_result['correct']}" if old_result else "not revealed"
    print(f"Round {arguments.round_id}: was {old_text}; now lie {arguments.statement}, correct={new_result['correct']}")


if __name__ == "__main__":
    main()
