from __future__ import annotations

from dataclasses import dataclass


CURRENT_USER = "li.wei"
LOCAL_TEST_SSH_IP = "192.168.1.15"
LOCAL_TEST_SSH_USER = "lon"
LOCAL_TEST_SSH_PASSWORD = "202188"


@dataclass(slots=True)
class Device:
    id: str
    name: str
    domain: str
    device_type: str
    cpu: str
    status: str
    owner: str | None
    ssh_ip: str
    telnet_ip: str
    username: str
    password: str
    vendor: str
    model: str
    site: str
    rack: str
    version: str
    notes: str


def sample_devices() -> list[Device]:
    return [
        Device(
            id="LOCAL-SSH-001",
            name="本机测试设备",
            domain="测试",
            device_type="Local SSH",
            cpu="hi1213",
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
            id="RTN-BJ-001",
            name="RTN-950A-BJ01",
            domain="\u0052\u0054\u004e",
            device_type="Microwave",
            cpu="hi1213",
            status="\u5df2\u88ab\u5360\u7528",
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
        ),
        Device(
            id="JQ-SH-003",
            name="JQ-Access-SH03",
            domain="\u4ea4\u4f01",
            device_type="Access Gateway",
            cpu="hi1215",
            status="\u7a7a\u95f2",
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
            domain="\u8def\u7531\u5668",
            device_type="Core Router",
            cpu="hi1260",
            status="\u6d41\u6c34\u7ebf\u5360\u7528",
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
            cpu="hi1215",
            status="\u7a7a\u95f2",
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
            domain="\u0052\u0054\u004e",
            device_type="Microwave",
            cpu="hi1213",
            status="\u5176\u4ed6",
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
    ]
