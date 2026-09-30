"""Network helpers used by the managed transfer service."""

from __future__ import annotations

import ipaddress
import socket

from .errors import UnsupportedOperationError


def normalize_advertised_host(value: str) -> str:
    raw = value.strip()
    if not raw or raw.casefold() == "auto":
        return ""
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise UnsupportedOperationError("设备访问地址必须是 IPv4 地址或留空自动选择。") from exc
    if not isinstance(address, ipaddress.IPv4Address):
        raise UnsupportedOperationError("设备访问地址目前仅支持 IPv4。")
    if address.is_unspecified or address.is_loopback or address.is_multicast:
        raise UnsupportedOperationError("设备访问地址必须是设备可达的本机 IPv4 地址。")
    return str(address)


def select_route_local_ipv4(remote_host: str, remote_port: int = 0) -> str:
    target = remote_host.strip()
    if not target:
        raise OSError("终端没有可用的远端地址。")
    port = int(remote_port) if 0 < int(remote_port) <= 65535 else 9
    errors: list[OSError] = []
    for family, socktype, protocol, _canonical, sockaddr in socket.getaddrinfo(
        target, port, family=socket.AF_INET, type=socket.SOCK_DGRAM
    ):
        probe = socket.socket(family, socktype, protocol)
        try:
            probe.connect(sockaddr)
            local_host = str(probe.getsockname()[0]).strip()
            address = ipaddress.ip_address(local_host)
            if isinstance(address, ipaddress.IPv4Address) and not (
                address.is_unspecified or address.is_loopback or address.is_multicast
            ):
                return str(address)
        except OSError as exc:
            errors.append(exc)
        finally:
            probe.close()
    if errors:
        raise OSError(str(errors[-1]))
    raise OSError(f"无法确定到 {target} 的本机 IPv4 路由。")
