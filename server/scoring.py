"""Reveal results and the Gemini vs. the Room scoreboard."""

from server import db

POINTS_FOR_CORRECT_CALL = 1
BONUS_WHEN_ROOM_MISSED = 1  # Gemini caught the lie while most of the room missed it


def compute_room_accuracy(votes: list[dict], lie_statement: int) -> float | None:
    if not votes:
        return None
    correct_votes = [vote for vote in votes if vote["statement"] == lie_statement]
    return round(len(correct_votes) / len(votes), 3)


def find_true_lie(round_info: dict, lie_statement_from_stage: int | None) -> tuple[int, str]:
    """Which statement was really the lie, and how we know.

    Players don't always lie on the statement the server picked for them, so the
    player's own answer wins over the secret.
    """
    if lie_statement_from_stage in [1, 2, 3]:
        return lie_statement_from_stage, "stage"
    if round_info.get("confirmed_lie_statement") in [1, 2, 3]:
        return round_info["confirmed_lie_statement"], "player_confirmed"
    return round_info["lie_index"] + 1, "secret"


def score_round_result(round_id: str, lie_statement: int, truth_source: str) -> dict:
    """Score one round against the true lie and save the result. Safe to run again."""
    round_info = db.get_round(round_id)
    call = round_info["call"]
    gemini_statement = call["statement"] if call else None

    votes = db.get_votes_for_round(round_id)
    room_accuracy = compute_room_accuracy(votes, lie_statement)
    gemini_was_correct = gemini_statement == lie_statement

    gemini_points = 0
    if gemini_was_correct:
        gemini_points += POINTS_FOR_CORRECT_CALL
        if room_accuracy is not None and room_accuracy < 0.5:
            gemini_points += BONUS_WHEN_ROOM_MISSED
    room_points = 1 if room_accuracy is not None and room_accuracy >= 0.5 else 0

    result = {
        "correct": gemini_was_correct,
        "lie_statement": lie_statement,
        "lie_index": lie_statement - 1,
        "truth_source": truth_source,
        "secret_lie_statement": round_info["lie_index"] + 1,
        "room_accuracy": room_accuracy,
        "gemini_statement": gemini_statement,
        "gemini_points": gemini_points,
        "room_points": room_points,
        "votes": votes,
    }
    db.save_round_json(round_id, "result_json", result)
    return result


def reveal_round(round_id: str, tried_to_trick: bool, lie_statement_from_stage: int | None = None) -> dict:
    """Return the /reveal contract shape: {correct, lie_index, room_accuracy, scoreboard}."""
    round_info = db.get_round(round_id)
    lie_statement, truth_source = find_true_lie(round_info, lie_statement_from_stage)
    db.save_tried_to_trick(round_id, tried_to_trick)
    result = score_round_result(round_id, lie_statement, truth_source)
    return {
        "correct": result["correct"],
        "lie_index": result["lie_index"],
        "room_accuracy": result["room_accuracy"],
        "scoreboard": build_scoreboard(round_info["room"]),
    }


def build_scoreboard(room: str) -> dict:
    """Totals for the room: Gemini points, Room points, and each voter's points."""
    gemini_total = 0
    room_total = 0
    points_by_voter = {}
    for revealed_round in db.get_revealed_rounds_in_room(room):
        result = revealed_round["result"]
        gemini_total += result["gemini_points"]
        room_total += result["room_points"]
        lie_statement = result.get("lie_statement", result["lie_index"] + 1)
        for vote in result["votes"]:
            points_by_voter.setdefault(vote["voter_name"], 0)
            if vote["statement"] == lie_statement:
                points_by_voter[vote["voter_name"]] += 1

    players = [{"name": name, "points": points} for name, points in points_by_voter.items()]
    players.sort(key=lambda player: player["points"], reverse=True)
    return {"gemini": gemini_total, "room": room_total, "players": players}
