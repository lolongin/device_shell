"""Runtime primitives for event-driven terminal workflows."""

from .matcher import TerminalMatcher
from .runner import MatchResult, wait_for_output

__all__ = ["MatchResult", "TerminalMatcher", "wait_for_output"]
