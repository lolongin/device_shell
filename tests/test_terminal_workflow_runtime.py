import asyncio

import pytest

from device_tui.application.workflow_runtime.matcher import TerminalMatcher


def test_matcher_matches_text_split_across_output_chunks():
    matcher = TerminalMatcher("contains", "Password:")

    assert matcher.feed("Pass") is False
    assert matcher.feed("word:\r\n") is True


def test_matcher_supports_case_insensitive_regex():
    matcher = TerminalMatcher("regex", r"ready\s+now", case_sensitive=False)

    assert matcher.feed("READY now") is True


def test_matcher_rejects_unknown_mode():
    with pytest.raises(ValueError, match="match mode"):
        TerminalMatcher("glob", "ready")


def test_wait_for_output_unsubscribes_after_match():
    asyncio.run(_wait_for_output_unsubscribes_after_match())


async def _wait_for_output_unsubscribes_after_match():
    from device_tui.application.workflow_runtime.runner import wait_for_output
    from device_tui.interfaces.desktop_api.session_hub import TerminalEvent

    class Hub:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.unsubscribed = False

        def subscribe(self, session_id, *, after_sequence=0):
            return self.queue, []

        def unsubscribe(self, session_id, queue):
            self.unsubscribed = True

    hub = Hub()
    await hub.queue.put(TerminalEvent("terminal.output", "s1", 1, data="READY"))
    result = await wait_for_output(hub, "s1", mode="contains", pattern="READY", timeout_seconds=1)

    assert result.status == "matched"
    assert hub.unsubscribed is True
