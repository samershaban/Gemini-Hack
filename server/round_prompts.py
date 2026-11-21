"""Prompt topics for two truths and a lie. Each round gets three different ones."""

import random

ALL_PROMPTS = [
    "A trip you took",
    "A food you can't stand",
    "Your first job",
    "A famous person you've met",
    "A skill you're secretly good at",
    "Something you broke",
    "A pet you've had",
    "The worst haircut you've had",
    "A concert you went to",
    "Something you won",
    "A sport you've played",
    "A weird thing in your room",
    "A time you got lost",
    "An injury you've had",
    "A language you speak",
    "Your favorite childhood show",
    "A place you've lived",
    "Something you're afraid of",
    "A celebrity you look like",
    "The last thing you cooked",
]


def pick_three_prompts() -> list[str]:
    """Return three different prompts, in random order."""
    return random.sample(ALL_PROMPTS, 3)


def pick_lie_index() -> int:
    """Secretly choose which of the three statements (0, 1, or 2) the player must lie about."""
    return random.randint(0, 2)
