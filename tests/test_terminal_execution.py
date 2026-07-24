from __future__ import annotations

from src.terminal_execution import (
    detect_terminal_prompt,
    incremental_terminal_output,
    strip_terminal_ansi,
)


def test_detect_terminal_prompt_supports_device_and_linux_prompts() -> None:
    assert detect_terminal_prompt("display version\r\nSimOS V1\r\n<sim> ") == "<sim>"
    assert detect_terminal_prompt("done\r\n<Core-1>") == "<Core-1>"
    assert detect_terminal_prompt("entered\r\n[Core-1]") == "[Core-1]"
    assert detect_terminal_prompt("ok\nadmin@host:~$ ") == "admin@host:~$"
    assert detect_terminal_prompt("ok\nroot@host:/# ") == "root@host:/#"


def test_prompt_detection_strips_ansi_and_ignores_regular_output() -> None:
    assert strip_terminal_ansi("\x1b[32mready\x1b[0m") == "ready"
    assert detect_terminal_prompt("\x1b[32mready\x1b[0m\n<Core>") == "<Core>"
    assert detect_terminal_prompt("progress 50%\noperation running") == ""


def test_incremental_output_uses_absolute_cursor() -> None:
    output, truncated = incremental_terminal_output(
        "3456789",
        buffer_start_cursor=3,
        output_cursor=10,
        requested_cursor=5,
        max_chars=100,
    )

    assert output == "56789"
    assert not truncated


def test_incremental_output_marks_trimmed_and_limited_content() -> None:
    trimmed, trimmed_flag = incremental_terminal_output(
        "56789",
        buffer_start_cursor=5,
        output_cursor=10,
        requested_cursor=2,
        max_chars=100,
    )
    limited, limited_flag = incremental_terminal_output(
        "0123456789",
        buffer_start_cursor=0,
        output_cursor=10,
        requested_cursor=0,
        max_chars=4,
    )

    assert trimmed == "56789"
    assert trimmed_flag
    assert limited == "6789"
    assert limited_flag
