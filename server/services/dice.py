from __future__ import annotations

import random
import re


def parse_dice(expression: str) -> tuple[int, list[int], int]:
    """Parse a dice expression like 'd20', '2d6+3', 'd100-5'.
    Returns (total, [individual_rolls], bonus).
    """
    expression = expression.strip().lower()
    bonus = 0
    rolls = []

    # Extract bonus/malus
    bonus_match = re.search(r'([+-]\d+)$', expression)
    if bonus_match:
        bonus = int(bonus_match.group(1))
        expression = expression[:bonus_match.start()].strip()

    # Parse XdY
    match = re.match(r'(\d+)?d(\d+)', expression)
    if not match:
        return 0, [], 0

    count = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))

    for _ in range(count):
        rolls.append(random.randint(1, sides))

    total = sum(rolls) + bonus
    return total, rolls, bonus


def roll(expression: str) -> dict:
    """Roll dice and return a structured result."""
    total, rolls, bonus = parse_dice(expression)
    return {
        "expression": expression,
        "total": total,
        "rolls": rolls,
        "bonus": bonus,
    }


def check_critical(rolls: list[int], sides: int) -> str | None:
    """Check for critical success or failure on d20 or d100."""
    if sides == 20:
        if rolls[0] == 20:
            return "critical_success"
        if rolls[0] == 1:
            return "critical_failure"
    if sides == 100:
        if rolls[0] <= 5:
            return "critical_success"
        if rolls[0] >= 96:
            return "critical_failure"
    return None
