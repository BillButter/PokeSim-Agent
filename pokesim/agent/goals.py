"""Goal management for the vision agent.

Goals are optional objectives provided by the user that guide the AI's decision-making.
If no goals are provided, the agent autonomously decides its own objectives.
"""

from __future__ import annotations

from typing import Any


def format_goals(goals: str | None) -> str:
    """Format user-provided goals for injection into prompts.
    
    If no goals provided, returns empty string and agent operates autonomously.
    """
    if not goals or not goals.strip():
        return ""
    
    lines = goals.strip().split("\n")
    # Filter out empty lines and limit to reasonable number
    goals_list = [line.strip() for line in lines if line.strip()][:20]
    if not goals_list:
        return ""
    
    formatted = "\n".join(f"- {goal}" for goal in goals_list)
    return (
        "GOALS FOR THIS SESSION\n"
        "The user has provided the following objectives. Work towards these while continuing to play:\n"
        f"{formatted}\n"
    )


def inject_goals_into_prompt(system_prompt: str, goals: str | None) -> str:
    """Inject formatted goals into the system prompt."""
    goals_section = format_goals(goals)
    if not goals_section:
        return system_prompt
    
    # Insert goals section after HOW TO PLAY section, before OUTPUT
    parts = system_prompt.split("\nOUTPUT\n")
    if len(parts) == 2:
        return parts[0] + "\n\n" + goals_section + "\nOUTPUT\n" + parts[1]
    return system_prompt


def validate_goals(value: Any) -> str:
    """Validate and normalize goals field."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Goals must be a string")
    # Limit to reasonable length (e.g., 2000 chars)
    text = value.strip()
    if len(text) > 2000:
        raise ValueError("Goals text is too long (max 2000 characters)")
    return text
