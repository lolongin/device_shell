"""Sample device data for local GUI testing."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from ..domain.devices.models import Device
from ..domain.devices.status import (
    STATUS_IDLE,
    STATUS_OCCUPIED,
    STATUS_OTHER,
    STATUS_PIPELINE,
)


CURRENT_USER = "li.wei"
LOCAL_TEST_SSH_IP = "192.168.1.15"
LOCAL_TEST_SSH_USER = "lon"
LOCAL_TEST_SSH_PASSWORD = "202188"
MOCK_DEVICE_HOST = "127.0.0.1"
MOCK_DEVICE_TELNET_USER = "lon"
MOCK_DEVICE_TELNET_PASSWORD = "202188"
MOCK_LINUX_SSH_USER = "ops"
MOCK_LINUX_SSH_PASSWORD = "ops123"
MOCK_PROTOCOL_FAILURE = os.getenv("DEVICE_TUI_MOCK_PROTOCOL_FAILURE") == "1"
MOCK_DEVICE_SSH_PORT = 0 if MOCK_PROTOCOL_FAILURE else 2200
MOCK_DEVICE_TELNET_PORT = 0 if MOCK_PROTOCOL_FAILURE else 2323
ENSP_AR_TELNET_IP = os.getenv("DEVICE_TUI_ENSP_AR_TELNET_IP", "192.168.40.20").strip()
ENSP_AR_TELNET_USER = os.getenv("DEVICE_TUI_ENSP_AR_TELNET_USER", "appadmin").strip()
# Keep the lab credential out of source control. The custom connection dialog
# can supply it for a one-time session when this is empty.
ENSP_AR_TELNET_PASSWORD = os.getenv("DEVICE_TUI_ENSP_AR_TELNET_PASSWORD", "").strip()
SAMPLE_NOW = datetime(2026, 6, 6, 8, 0, tzinfo=timezone.utc)

def sample_devices() -> list[Device]:
    devices = [
        Device(
            id="MOCK-LAB-000",
            name="Mock-Huawei-Lab",
            domain="测试",
            device_type="Mock Device",
            cpu="ARM-0",
            status="空闲",
            owner=None,
            ssh_ip=MOCK_DEVICE_HOST,
            telnet_ip=MOCK_DEVICE_HOST,
            username=MOCK_DEVICE_TELNET_USER,
            password=MOCK_DEVICE_TELNET_PASSWORD,
            vendor="Huawei / Local Lab",
            model="Local GUI Sample",
            site="Localhost",
            rack="Local-R01",
            version="Telnet:2323 / SSH:2200",
            notes="Local GUI sample device. Configure matching Telnet and SSH endpoints before using it for connection tests.",
            ssh_port=MOCK_DEVICE_SSH_PORT,
            telnet_port=MOCK_DEVICE_TELNET_PORT,
            ssh_username=MOCK_LINUX_SSH_USER,
            ssh_password=MOCK_LINUX_SSH_PASSWORD,
            serial_ip=MOCK_DEVICE_HOST,
            serial_port=MOCK_DEVICE_TELNET_PORT,
            serial_username=MOCK_DEVICE_TELNET_USER,
            serial_password=MOCK_DEVICE_TELNET_PASSWORD,
            supports_power_off=True,
        ),
        Device(
            id="LOCAL-SSH-001",
            name="本机测试设备",
            domain="测试",
            device_type="Local SSH",
            cpu="ARM-1",
            status="空闲",
            owner=None,
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="127.0.0.1",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Microsoft OpenSSH",
            model="Windows Localhost",
            site="Local Machine",
            rack="N/A",
            version="OpenSSH_for_Windows_9.5p2",
            notes="专用于本机 SSH 联调。按 s 可直接测试连接。",
        ),
        Device(
            id="ENSP-AR-001",
            name="eNSP-Pro-AR-1",
            domain="测试",
            device_type="AR Router",
            cpu="Virtual",
            status=STATUS_IDLE,
            owner=None,
            ssh_ip="",
            telnet_ip=ENSP_AR_TELNET_IP,
            username=ENSP_AR_TELNET_USER,
            password=ENSP_AR_TELNET_PASSWORD,
            vendor="Huawei",
            model="eNSP Pro AR",
            site="Local eNSP Pro",
            rack="VMnet3",
            version="Telnet / GE0/0/0",
            notes="本地 eNSP Pro AR 测试设备。未配置密码时，请在设备详情中使用 Telnet 编辑按钮输入凭据。",
            telnet_port=23,
        ),
        Device(
            id="RTN-BJ-001",
            name="RTN-950A-BJ01",
            domain="RTN",
            device_type="Microwave",
            cpu="ARM-2",
            status="已被占用",
            owner="li.wei",
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.16.1.11",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Huawei",
            model="RTN 950A",
            site="Beijing Tongzhou",
            rack="A01-U08",
            version="V100R019C10",
            notes="Backhaul node for aggregation ring. SSH points to local host for testing.",
            supports_power_off=True,
            extra={"occupancy_started_at": (SAMPLE_NOW - timedelta(hours=2, minutes=15)).isoformat()},
        ),
        Device(
            id="JQ-SH-003",
            name="JQ-Access-SH03",
            domain="交企",
            device_type="Access Gateway",
            cpu="ARM-3",
            status="空闲",
            owner=None,
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.20.3.21",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="H3C",
            model="SecPath F1000",
            site="Shanghai Pudong",
            rack="B12-U16",
            version="R7608P30",
            notes="Traffic enterprise edge gateway. SSH points to local host for testing.",
        ),
        Device(
            id="RTR-GZ-006",
            name="Core-Router-GZ06",
            domain="路由器",
            device_type="Core Router",
            cpu="ARM-4",
            status="流水线占用",
            owner="pipeline.bot",
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.30.6.1",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Cisco",
            model="ASR 1006-X",
            site="Guangzhou Tianhe",
            rack="C03-U20",
            version="IOS-XE 17.09",
            notes="Reserved by backbone pipeline validation job. SSH points to local host for testing.",
        ),
        Device(
            id="XTN-CD-002",
            name="XTN-Node-CD02",
            domain="XTN",
            device_type="Transport Node",
            cpu="ARM-5",
            status="空闲",
            owner=None,
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.40.2.18",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Huawei",
            model="OptiXtrans XTN 980",
            site="Chengdu Hi-Tech",
            rack="D07-U11",
            version="V100R021C00",
            notes="Metro transport node with spare capacity. SSH points to local host for testing.",
        ),
        Device(
            id="RTN-SZ-009",
            name="RTN-Hop-SZ09",
            domain="RTN",
            device_type="Microwave",
            cpu="ARM-6",
            status="其他",
            owner="li.wei",
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.16.9.9",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Huawei",
            model="RTN 980",
            site="Shenzhen Nanshan",
            rack="E02-U05",
            version="V100R018C00",
            notes="Temporarily held for antenna alignment and field handoff. SSH points to local host for testing.",
        ),
        Device(
            id="LAB-BJ-010",
            name="Lab-Gateway-BJ10",
            domain="测试",
            device_type="Validation Gateway",
            cpu="ARM-7",
            status="空闲",
            owner=None,
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.10.10",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Huawei",
            model="Lab GW 1000",
            site="Beijing Lab",
            rack="F01-U02",
            version="V200R001C00",
            notes="Added to expand CPU filter coverage.",
        ),
        Device(
            id="JQ-HZ-011",
            name="JQ-Edge-HZ11",
            domain="交企",
            device_type="Edge Gateway",
            cpu="ARM-8",
            status="已被占用",
            owner="li.wei",
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.11.11",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="H3C",
            model="SecPath F5000",
            site="Hangzhou Binjiang",
            rack="F02-U08",
            version="R7801P12",
            notes="Added to expand CPU filter coverage.",
        ),
        Device(
            id="RTR-SH-012",
            name="Metro-Router-SH12",
            domain="路由器",
            device_type="Metro Router",
            cpu="ARM-9",
            status="空闲",
            owner=None,
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.12.12",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Cisco",
            model="NCS 540",
            site="Shanghai Minhang",
            rack="F03-U09",
            version="IOS-XR 7.8.1",
            notes="Added to expand CPU filter coverage.",
        ),
        Device(
            id="XTN-WH-013",
            name="XTN-Agg-WH13",
            domain="XTN",
            device_type="Transport Aggregation",
            cpu="ARM-10",
            status="其他",
            owner="ops.shift",
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.13.13",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Huawei",
            model="OptiXtrans XTN 900",
            site="Wuhan Optical Valley",
            rack="F04-U10",
            version="V100R022C00",
            notes="Added to expand CPU filter coverage.",
        ),
        Device(
            id="RTN-XA-014",
            name="RTN-Link-XA14",
            domain="RTN",
            device_type="Backhaul Radio",
            cpu="ARM-11",
            status="空闲",
            owner=None,
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.14.14",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Huawei",
            model="RTN 380AX",
            site="Xian Yanta",
            rack="F05-U05",
            version="V100R017C20",
            notes="Added to expand CPU filter coverage.",
        ),
        Device(
            id="JQ-SZ-015",
            name="JQ-Branch-SZ15",
            domain="交企",
            device_type="Branch Security Gateway",
            cpu="ARM-12",
            status="流水线占用",
            owner="pipeline.bot",
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.15.15",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="H3C",
            model="SecPath M9000",
            site="Shenzhen Futian",
            rack="F06-U12",
            version="R7905P03",
            notes="Added to expand CPU filter coverage.",
        ),
        Device(
            id="RTR-CD-016",
            name="Core-Router-CD16",
            domain="路由器",
            device_type="Core Router",
            cpu="ARM-13",
            status="空闲",
            owner=None,
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.16.16",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Cisco",
            model="ASR 9902",
            site="Chengdu Tianfu",
            rack="F07-U15",
            version="IOS-XR 7.7.2",
            notes="Added to expand CPU filter coverage.",
        ),
        Device(
            id="LAB-GZ-017",
            name="Perf-Node-GZ17",
            domain="测试",
            device_type="Performance Test Node",
            cpu="ARM-14",
            status="已被占用",
            owner="qa.bot",
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.17.17",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Dell",
            model="R740xd",
            site="Guangzhou Lab",
            rack="F08-U18",
            version="Ubuntu 22.04",
            notes="Added to expand CPU filter coverage.",
        ),
        Device(
            id="XTN-NJ-018",
            name="XTN-Hub-NJ18",
            domain="XTN",
            device_type="Transport Hub",
            cpu="ARM-15",
            status="其他",
            owner="li.wei",
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.18.18",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Huawei",
            model="OptiXtrans XTN 960",
            site="Nanjing Jiangning",
            rack="F09-U07",
            version="V100R020C30",
            notes="Added to expand CPU filter coverage.",
        ),
        Device(
            id="RTR-TJ-019",
            name="Border-Router-TJ19",
            domain="路由器",
            device_type="Border Router",
            cpu="ARM-16",
            status="空闲",
            owner=None,
            ssh_ip=LOCAL_TEST_SSH_IP,
            telnet_ip="172.18.19.19",
            username=LOCAL_TEST_SSH_USER,
            password=LOCAL_TEST_SSH_PASSWORD,
            vendor="Juniper",
            model="MX204",
            site="Tianjin Binhai",
            rack="F10-U04",
            version="Junos 22.3R1",
            notes="Added to expand CPU filter coverage.",
        ),
    ]
    return _expand_frame_device_samples(_with_board_ids(devices))


def _expand_frame_device_samples(devices: list[Device]) -> list[Device]:
    expanded: list[Device] = []
    for device in devices:
        if device.id == "XTN-NJ-018":
            expanded.extend(_xtn_nj_018_boards(device))
            continue
        expanded.append(device)
    return expanded


def _xtn_nj_018_boards(device: Device) -> list[Device]:
    board_specs = [
        ("1", "MPU", "ARM-15", "F09-U01"),
        ("2", "SFU", "ARM-15", "F09-U02"),
        ("5", "LPU", "ARM-15", "F09-U05"),
        ("8", "PIU", "ARM-15", "F09-U08"),
    ]
    boards: list[Device] = []
    for slot_id, board_role, cpu, rack in board_specs:
        boards.append(
            Device(
                id=device.id,
                board_id=f"{device.id}-{slot_id}",
                name=device.name,
                domain=device.domain,
                device_type=board_role,
                cpu=cpu,
                status=device.status,
                owner=device.owner,
                ssh_ip=device.ssh_ip,
                telnet_ip=device.telnet_ip,
                username=device.username,
                password=device.password,
                vendor=device.vendor,
                model=device.model,
                site=device.site,
                rack=rack,
                version=device.version,
                notes="Frame device sample with multiple boards. SSH points to local host for testing.",
                ssh_port=device.ssh_port,
                telnet_port=device.telnet_port,
                ssh_username=device.ssh_username,
                ssh_password=device.ssh_password,
                serial_ip="172.18.200.18",
                serial_port=2000,
                serial_username=device.serial_username,
                serial_password=device.serial_password,
                supports_power_off=device.supports_power_off,
                extra={
                    "slot_id": slot_id,
                    "board_role": board_role,
                    "board_type": "XTN960",
                    "subdomain": "SDK",
                    "hardware_platform": "云杉",
                    "serial_server": "172.18.200.18",
                },
            )
        )
    return boards


def _with_board_ids(devices: list[Device]) -> list[Device]:
    for index, device in enumerate(devices, start=1):
        if not device.board_id:
            device.board_id = f"{index:04d}"
    return devices


def large_sample_devices(count: int) -> list[Device]:
    devices = sample_devices()
    if count <= len(devices):
        return devices[:count]

    domains = ["RTN", "XTN", "交企", "路由器", "测试"]
    device_types = [
        "Microwave",
        "Transport Node",
        "Access Gateway",
        "Core Router",
        "Validation Node",
    ]
    vendors = ["Huawei", "H3C", "Cisco", "Juniper", "ZTE"]
    models = ["RTN 950A", "XTN 980", "SecPath F1000", "NCS 540", "Lab GW 1000"]
    sites = [
        "Beijing Tongzhou",
        "Shanghai Pudong",
        "Guangzhou Tianhe",
        "Chengdu Hi-Tech",
        "Shenzhen Nanshan",
        "Nanjing Jiangning",
        "Wuhan Optical Valley",
        "Hangzhou Binjiang",
    ]
    name_prefixes = ["RTN", "XTN", "JQ", "RTR", "LAB"]
    status_cycle = [
        (STATUS_IDLE, None),
        (STATUS_OCCUPIED, CURRENT_USER),
        (STATUS_IDLE, None),
        (STATUS_PIPELINE, "pipeline.bot"),
        (STATUS_OTHER, "ops.shift"),
        (STATUS_OCCUPIED, "qa.bot"),
    ]

    for index in range(len(devices) + 1, count + 1):
        offset = index - 1
        status, owner = status_cycle[offset % len(status_cycle)]
        domain = domains[offset % len(domains)]
        subnet_a = 10 + (offset // 250) % 120
        subnet_b = (offset // 250) % 255
        host = offset % 250 + 1
        devices.append(
            Device(
                id=f"MOCK-{index:04d}",
                name=f"{name_prefixes[offset % len(name_prefixes)]}-Node-{index:04d}",
                domain=domain,
                device_type=device_types[offset % len(device_types)],
                cpu=f"ARM-{offset % 16}",
                status=status,
                owner=owner,
                ssh_ip=LOCAL_TEST_SSH_IP,
                telnet_ip=f"172.{subnet_a}.{subnet_b}.{host}",
                username=LOCAL_TEST_SSH_USER,
                password=LOCAL_TEST_SSH_PASSWORD,
                vendor=vendors[offset % len(vendors)],
                model=models[offset % len(models)],
                site=sites[offset % len(sites)],
                rack=f"R{offset % 40 + 1:02d}-U{offset % 42 + 1:02d}",
                version=f"V{100 + offset % 9}R{offset % 24:02d}C{offset % 10:02d}",
                notes=f"Generated performance sample device #{index}.",
                ssh_port=22,
                telnet_port=23,
                ssh_username=LOCAL_TEST_SSH_USER,
                ssh_password=LOCAL_TEST_SSH_PASSWORD,
                serial_ip=f"10.{subnet_a}.{subnet_b}.{host}",
                serial_port=2000 + offset % 1000,
                serial_username=LOCAL_TEST_SSH_USER,
                serial_password=LOCAL_TEST_SSH_PASSWORD,
                supports_power_off=owner == CURRENT_USER or index % 7 == 0,
                board_id=f"{index:04d}",
                extra=(
                    {"occupancy_started_at": (SAMPLE_NOW - timedelta(minutes=15 + offset * 3)).isoformat()}
                    if status == STATUS_OCCUPIED
                    else {}
                ),
            )
        )

    return devices
