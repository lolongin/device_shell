from device_tui.interfaces.desktop_api.secret_filter import SecretOutputFilter


def test_secret_filter_redacts_secret_split_across_chunks() -> None:
    output_filter = SecretOutputFilter(("sensitive-password",))

    rendered = "".join(
        (
            output_filter.feed("login: user\npass: sensitive-"),
            output_filter.feed("pass"),
            output_filter.feed("word\n<device>"),
            output_filter.flush(),
        )
    )

    assert "sensitive-password" not in rendered
    assert "***" in rendered
    assert rendered.endswith("\n<device>")


def test_secret_filter_prefers_longest_overlapping_secret() -> None:
    output_filter = SecretOutputFilter(("token", "token-long"))

    rendered = output_filter.feed("value=token-long;") + output_filter.flush()

    assert rendered == "value=***;"


def test_secret_filter_without_secrets_does_not_delay_output() -> None:
    output_filter = SecretOutputFilter(())

    assert output_filter.feed("prompt>") == "prompt>"
    assert output_filter.flush() == ""
