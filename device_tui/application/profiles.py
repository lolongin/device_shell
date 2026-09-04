"""Connection profiles for temporary devices and saved SSH servers."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from device_tui.domain.devices.temporary import deserialize_temporary_device
from .credentials import ConnectionTarget, CredentialResolver, SessionCredential, SessionProtocol
from .errors import ApplicationConflictError, ResourceNotFoundError, UnsupportedOperationError
from .secrets import SecretStore


ProfileType = Literal["temporary", "server"]


@dataclass(frozen=True, slots=True)
class ProfileEndpoint:
    host: str = ""
    port: int = 0
    username: str = ""


@dataclass(frozen=True, slots=True)
class ConnectionProfile:
    id: str
    profile_type: ProfileType
    name: str
    group: str = ""
    notes: str = ""
    preferred_protocol: SessionProtocol = "ssh"
    telnet: ProfileEndpoint = ProfileEndpoint(port=23)
    ssh: ProfileEndpoint = ProfileEndpoint(port=22)
    serial: ProfileEndpoint = ProfileEndpoint(port=23)
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class ConnectionProfileDraft:
    profile_type: ProfileType
    name: str
    group: str = ""
    notes: str = ""
    preferred_protocol: SessionProtocol = "ssh"
    telnet: ProfileEndpoint = ProfileEndpoint(port=23)
    ssh: ProfileEndpoint = ProfileEndpoint(port=22)
    serial: ProfileEndpoint = ProfileEndpoint(port=23)
    passwords: dict[str, str | None] | None = None
    profile_id: str = ""
    created_at: str = ""


class ConnectionProfileStore(Protocol):
    def list_profiles(self) -> list[ConnectionProfile]: ...

    def get_profile(self, profile_id: str) -> ConnectionProfile | None: ...

    def upsert_profile(self, profile: ConnectionProfile) -> None: ...

    def delete_profile(self, profile_id: str) -> None: ...

    def list_groups(self) -> list[str]: ...

    def add_group(self, name: str) -> None: ...

    def get_meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...


class MemoryConnectionProfileStore:
    def __init__(self) -> None:
        self._profiles: dict[str, ConnectionProfile] = {}
        self._groups: list[str] = []
        self._meta: dict[str, str] = {}

    def list_profiles(self) -> list[ConnectionProfile]:
        return sorted(
            self._profiles.values(),
            key=lambda profile: (profile.profile_type, profile.group, profile.name, profile.id),
        )

    def get_profile(self, profile_id: str) -> ConnectionProfile | None:
        return self._profiles.get(profile_id)

    def upsert_profile(self, profile: ConnectionProfile) -> None:
        self._profiles[profile.id] = profile

    def delete_profile(self, profile_id: str) -> None:
        self._profiles.pop(profile_id, None)

    def list_groups(self) -> list[str]:
        return list(self._groups)

    def add_group(self, name: str) -> None:
        normalized = name.strip()
        if normalized and normalized not in self._groups:
            self._groups.append(normalized)

    def get_meta(self, key: str) -> str | None:
        return self._meta.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self._meta[key] = value


class ConnectionProfileService:
    LEGACY_IMPORT_KEY = "legacy_desktop_state_v1"

    def __init__(self, store: ConnectionProfileStore, secrets: SecretStore) -> None:
        self._store = store
        self._secrets = secrets

    def list_profiles(self, profile_type: ProfileType | None = None) -> list[ConnectionProfile]:
        profiles = self._store.list_profiles()
        if profile_type is not None:
            profiles = [profile for profile in profiles if profile.profile_type == profile_type]
        return profiles

    def get_profile(self, profile_id: str) -> ConnectionProfile:
        profile = self._store.get_profile(profile_id)
        if profile is None:
            raise ResourceNotFoundError(
                f"Unknown connection profile: {profile_id}",
                details={"resource": "connection_profile", "profile_id": profile_id},
            )
        return profile

    def save(
        self,
        draft: ConnectionProfileDraft,
        *,
        allow_duplicate: bool = False,
    ) -> ConnectionProfile:
        profile = self._validated_profile(draft)
        for candidate in self._store.list_profiles():
            if candidate.id == profile.id:
                continue
            if (
                not allow_duplicate
                and candidate.profile_type == profile.profile_type
                and candidate.ssh.host.casefold() == profile.ssh.host.casefold()
                and candidate.ssh.host
                and candidate.ssh.port == profile.ssh.port
            ):
                raise ApplicationConflictError(
                    f"A connection profile already uses {profile.ssh.host}:{profile.ssh.port}",
                    details={"profile_id": candidate.id},
                )
        previous = self._store.get_profile(profile.id)
        previous_secrets = {
            protocol: self._secrets.get(self.secret_id(profile.id, protocol))
            for protocol in ("telnet", "ssh", "serial")
        }
        self._store.upsert_profile(profile)
        try:
            for protocol, password in (draft.passwords or {}).items():
                if protocol not in {"telnet", "ssh", "serial"} or password is None:
                    continue
                secret_id = self.secret_id(profile.id, protocol)
                if password:
                    self._secrets.set(secret_id, password)
                else:
                    self._secrets.delete(secret_id)
        except Exception:
            if previous is None:
                self._store.delete_profile(profile.id)
            else:
                self._store.upsert_profile(previous)
            for protocol, password in previous_secrets.items():
                secret_id = self.secret_id(profile.id, protocol)
                if password is None:
                    self._secrets.delete(secret_id)
                else:
                    self._secrets.set(secret_id, password)
            raise
        if profile.group:
            self._store.add_group(profile.group)
        return profile

    def delete(self, profile_id: str) -> None:
        self.get_profile(profile_id)
        self._store.delete_profile(profile_id)
        for protocol in ("telnet", "ssh", "serial"):
            self._secrets.delete(self.secret_id(profile_id, protocol))

    def list_groups(self) -> list[str]:
        return self._store.list_groups()

    def create_group(self, name: str) -> str:
        normalized = name.strip()
        if not normalized or normalized == "未分组":
            raise UnsupportedOperationError("A connection-profile group name is required.")
        self._store.add_group(normalized)
        return normalized

    def has_password(self, profile_id: str, protocol: str) -> bool:
        return self._secrets.get(self.secret_id(profile_id, protocol)) is not None

    def password(self, profile_id: str, protocol: str) -> str:
        """Return the saved profile password for local configuration editing."""
        self.get_profile(profile_id)
        if protocol not in {"telnet", "ssh", "serial"}:
            raise UnsupportedOperationError(
                f"Unsupported profile protocol: {protocol}",
                details={"profile_id": profile_id, "protocol": protocol},
            )
        return self._secrets.get(self.secret_id(profile_id, protocol)) or ""

    def set_password(self, profile_id: str, protocol: str, password: str) -> None:
        profile = self.get_profile(profile_id)
        if protocol not in {"telnet", "ssh", "serial"}:
            raise UnsupportedOperationError(
                f"Unsupported profile protocol: {protocol}",
                details={"profile_id": profile_id, "protocol": protocol},
            )
        endpoint = getattr(profile, protocol)
        if not endpoint.host:
            raise UnsupportedOperationError(
                f"Profile has no {protocol} endpoint: {profile.id}",
                details={"profile_id": profile.id, "protocol": protocol},
            )
        secret_id = self.secret_id(profile.id, protocol)
        if password:
            self._secrets.set(secret_id, password)
        else:
            self._secrets.delete(secret_id)

    def resolve_target(self, profile_id: str, protocol: SessionProtocol) -> ConnectionTarget:
        profile = self.get_profile(profile_id)
        if protocol == "simulated":
            return ConnectionTarget(profile.id, protocol, "", 0)
        endpoint = getattr(profile, protocol)
        if not endpoint.host:
            raise UnsupportedOperationError(
                f"Profile has no {protocol} endpoint: {profile.id}",
                details={"profile_id": profile.id, "protocol": protocol},
            )
        password = self._secrets.get(self.secret_id(profile.id, protocol))
        if password is None:
            raise UnsupportedOperationError(
                f"Profile has no saved {protocol} credential: {profile.id}",
                details={"profile_id": profile.id, "protocol": protocol},
            )
        return self.resolve_target_with_password(profile_id, protocol, password)

    def resolve_target_with_password(
        self,
        profile_id: str,
        protocol: SessionProtocol,
        password: str,
    ) -> ConnectionTarget:
        profile = self.get_profile(profile_id)
        if protocol == "simulated":
            raise UnsupportedOperationError("Connection profiles do not support simulated sessions.")
        endpoint = getattr(profile, protocol)
        if not endpoint.host:
            raise UnsupportedOperationError(
                f"Profile has no {protocol} endpoint: {profile.id}",
                details={"profile_id": profile.id, "protocol": protocol},
            )
        if not password:
            raise UnsupportedOperationError(
                f"A {protocol} password is required: {profile.id}",
                details={"profile_id": profile.id, "protocol": protocol},
            )
        username = endpoint.username or ("root" if profile.profile_type == "server" and protocol == "ssh" else "")
        return ConnectionTarget(
            device_id=profile.id,
            protocol=protocol,
            host=endpoint.host,
            port=endpoint.port,
            credentials=(SessionCredential(username, password),),
        )

    def import_legacy_state(self, state_path: Path) -> dict[str, int]:
        if self._store.get_meta(self.LEGACY_IMPORT_KEY) is not None or not state_path.exists():
            return {"temporary": 0, "servers": 0, "groups": 0}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"temporary": 0, "servers": 0, "groups": 0}
        if not isinstance(payload, dict):
            return {"temporary": 0, "servers": 0, "groups": 0}
        counts = {"temporary": 0, "servers": 0, "groups": 0}
        groups = payload.get("saved_server_groups", [])
        if isinstance(groups, list):
            for value in groups:
                name = str(value or "").strip()
                if name:
                    self._store.add_group(name)
                    counts["groups"] += 1
        temporary = payload.get("temporary_devices", [])
        if isinstance(temporary, list):
            for item in temporary:
                device = deserialize_temporary_device(item)
                if device is None:
                    continue
                preferred = {"device": "telnet", "linux": "ssh", "serial": "serial"}.get(
                    str(device.extra.get("preferred_kind") or "device"),
                    "telnet",
                )
                self.save(
                    ConnectionProfileDraft(
                        profile_type="temporary",
                        profile_id=device.id,
                        name=device.name,
                        notes=device.notes,
                        preferred_protocol=preferred,  # type: ignore[arg-type]
                        telnet=ProfileEndpoint(device.telnet_ip, device.telnet_port, device.username),
                        ssh=ProfileEndpoint(device.ssh_ip, device.ssh_port, device.ssh_username),
                        serial=ProfileEndpoint(device.serial_ip, device.serial_port, device.serial_username),
                        passwords={
                            "telnet": device.password,
                            "ssh": device.ssh_password,
                            "serial": device.serial_password,
                        },
                        created_at=str(device.extra.get("created_at") or ""),
                    ),
                    # Legacy UI allowed duplicate endpoints. Migration must be
                    # lossless; the new duplicate guard applies to later edits.
                    allow_duplicate=True,
                )
                counts["temporary"] += 1
        servers = payload.get("saved_servers", [])
        if isinstance(servers, list):
            for item in servers:
                if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                    continue
                self.save(
                    ConnectionProfileDraft(
                        profile_type="server",
                        profile_id=str(item["id"]).strip(),
                        name=str(item.get("name") or item["id"]).strip(),
                        group=str(item.get("group") or "").strip(),
                        notes=str(item.get("notes") or "").strip(),
                        preferred_protocol="ssh",
                        ssh=ProfileEndpoint(
                            str(item.get("host") or "").strip(),
                            self._port(item.get("port"), 22),
                            str(item.get("username") or "").strip(),
                        ),
                        passwords={"ssh": str(item.get("password") or "")},
                    ),
                    allow_duplicate=True,
                )
                counts["servers"] += 1
        self._store.set_meta(
            self.LEGACY_IMPORT_KEY,
            json.dumps({"imported_at": self._now(), **counts}, ensure_ascii=False),
        )
        return counts

    def _validated_profile(self, draft: ConnectionProfileDraft) -> ConnectionProfile:
        name = draft.name.strip()
        if not name:
            raise UnsupportedOperationError("A connection profile name is required.")
        endpoints = {
            "telnet": self._endpoint(draft.telnet, 23),
            "ssh": self._endpoint(draft.ssh, 22),
            "serial": self._endpoint(draft.serial, 23),
        }
        if draft.profile_type == "server":
            endpoints["telnet"] = ProfileEndpoint(port=23)
            endpoints["serial"] = ProfileEndpoint(port=23)
        else:
            for protocol in ("telnet", "ssh"):
                endpoint = endpoints[protocol]
                if endpoint.host and not endpoint.username:
                    raise UnsupportedOperationError(
                        f"A {protocol} username is required when its endpoint is configured.",
                        details={"protocol": protocol},
                    )
        if not any(endpoint.host for endpoint in endpoints.values()):
            raise UnsupportedOperationError("At least one connection endpoint is required.")
        preferred = draft.preferred_protocol
        if preferred == "simulated" or not endpoints[preferred].host:
            preferred = next(
                protocol for protocol in ("ssh", "telnet", "serial") if endpoints[protocol].host
            )  # type: ignore[assignment]
        now = self._now()
        previous = self._store.get_profile(draft.profile_id) if draft.profile_id else None
        prefix = "TEMP" if draft.profile_type == "temporary" else "SERVER"
        return ConnectionProfile(
            id=draft.profile_id.strip() or f"{prefix}-{uuid4().hex[:12].upper()}",
            profile_type=draft.profile_type,
            name=name,
            group=draft.group.strip(),
            notes=draft.notes.strip(),
            preferred_protocol=preferred,
            telnet=endpoints["telnet"],
            ssh=endpoints["ssh"],
            serial=endpoints["serial"],
            created_at=draft.created_at or (previous.created_at if previous else now),
            updated_at=now,
        )

    @staticmethod
    def _endpoint(endpoint: ProfileEndpoint, default_port: int) -> ProfileEndpoint:
        return replace(
            endpoint,
            host=endpoint.host.strip(),
            port=ConnectionProfileService._port(endpoint.port, default_port),
            username=endpoint.username.strip(),
        )

    @staticmethod
    def _port(value: object, default: int) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            return default
        return port if 1 <= port <= 65535 else default

    @staticmethod
    def secret_id(profile_id: str, protocol: str) -> str:
        return f"connection-profile:{profile_id}:{protocol}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


class ProfileCredentialResolver:
    def __init__(self, profiles: ConnectionProfileService) -> None:
        self._profiles = profiles

    def resolve(self, device_id: str, protocol: SessionProtocol) -> ConnectionTarget:
        return self._profiles.resolve_target(device_id, protocol)


class CompositeCredentialResolver:
    def __init__(
        self,
        repository: CredentialResolver,
        profiles: ConnectionProfileService,
    ) -> None:
        self._repository = repository
        self._profiles = profiles

    def resolve(self, device_id: str, protocol: SessionProtocol) -> ConnectionTarget:
        if any(profile.id == device_id for profile in self._profiles.list_profiles()):
            return self._profiles.resolve_target(device_id, protocol)
        return self._repository.resolve(device_id, protocol)
