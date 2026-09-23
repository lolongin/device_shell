"""Runtime primitives for event-driven terminal workflows."""

from .matcher import TerminalMatcher
from .output_contract import COMMAND_OUTPUT_SCHEMA, normalize_command_output
from .runner import MatchResult, wait_for_output

__all__ = [
    "COMMAND_OUTPUT_SCHEMA",
    "MatchResult",
    "TerminalMatcher",
    "normalize_command_output",
    "wait_for_output",
]
