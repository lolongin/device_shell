"""Secret storage boundary backed by the operating-system credential vault."""

from __future__ import annotations

from threading import Lock
from typing import Protocol

from .errors import ApplicationError


class SecretStore(Protocol):
    def get(self, secret_id: str) -> str | None: ...

    def set(self, secret_id: str, value: str) -> None: ...

    def delete(self, secret_id: str) -> None: ...


class MemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = Lock()

    def get(self, secret_id: str) -> str | None:
        with self._lock:
            return self._values.get(secret_id)

    def set(self, secret_id: str, value: str) -> None:
        with self._lock:
            self._values[secret_id] = value

    def delete(self, secret_id: str) -> None:
        with self._lock:
            self._values.pop(secret_id, None)


class KeyringSecretStore:
    """Use python-keyring without providing an insecure plaintext fallback."""

    def __init__(self, service_name: str = "odyterm") -> None:
        self._service_name = service_name

    def get(self, secret_id: str) -> str | None:
        try:
            import keyring

            return keyring.get_password(self._service_name, secret_id)
        except Exception as exc:
            raise ApplicationError("The operating-system credential store is unavailable.") from exc

    def set(self, secret_id: str, value: str) -> None:
        try:
            import keyring

            keyring.set_password(self._service_name, secret_id, value)
        except Exception as exc:
            raise ApplicationError("Unable to save a credential in the operating-system vault.") from exc

    def delete(self, secret_id: str) -> None:
        try:
            import keyring
            from keyring.errors import PasswordDeleteError

            try:
                keyring.delete_password(self._service_name, secret_id)
            except PasswordDeleteError:
                pass
        except Exception as exc:
            raise ApplicationError("Unable to delete a credential from the operating-system vault.") from exc
