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


# Easy questions everyone can answer truthfully without thinking, so the baseline shows
# how the player talks when they're relaxed and honest.
ALL_BASELINE_PROMPTS = [
    "Say your name and where you're from.",
    "What did you eat today?",
    "How did you get here today?",
    "What do you do for work or school?",
    "What's the weather like outside?",
    "What's your favorite food?",
]


def pick_two_baseline_prompts() -> list[str]:
    """The first one is always the name question; the second is random."""
    return [ALL_BASELINE_PROMPTS[0], random.choice(ALL_BASELINE_PROMPTS[1:])]


def pick_three_prompts() -> list[str]:
    """Return three different prompts, in random order."""
    return random.sample(ALL_PROMPTS, 3)

