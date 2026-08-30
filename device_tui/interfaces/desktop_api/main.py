"""Process entry point supervised by Electron Main."""

from __future__ import annotations

import argparse
import json
import os
import socket

import uvicorn

from .app import create_app
from .models import API_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OdyTerm desktop backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=0, type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    token = os.getenv("DEVICE_TUI_DESKTOP_TOKEN", "")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(128)
    port = int(listener.getsockname()[1])
    print(
        json.dumps(
            {
                "type": "ready",
                "host": args.host,
                "port": port,
                "apiVersion": API_VERSION,
            }
        ),
        flush=True,
    )
    config = uvicorn.Config(
        create_app(token=token),
        host=args.host,
        port=port,
        log_level=os.getenv("DEVICE_TUI_BACKEND_LOG_LEVEL", "warning"),
    )
    server = uvicorn.Server(config)
    server.run(sockets=[listener])


if __name__ == "__main__":
    main()
