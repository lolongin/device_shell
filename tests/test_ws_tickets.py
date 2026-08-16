from device_tui.interfaces.desktop_api.ws_tickets import WebSocketTicketStore


def test_websocket_ticket_is_scoped_and_single_use() -> None:
    store = WebSocketTicketStore()
    ticket = store.issue("terminal", "session-1")

    assert not store.consume(ticket.value, "terminal", "session-2")
    assert not store.consume(ticket.value, "terminal", "session-1")

    valid = store.issue("terminal", "session-1")
    assert store.consume(valid.value, "terminal", "session-1")
    assert not store.consume(valid.value, "terminal", "session-1")


def test_event_ticket_rejects_terminal_scope() -> None:
    store = WebSocketTicketStore()
    ticket = store.issue("events")

    assert not store.consume(ticket.value, "terminal")
