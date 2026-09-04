"""Tool schemas exposed to the language model."""

from __future__ import annotations

TERMINAL_EXECUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "terminal_execute",
        "description": "在当前设备终端执行一条命令，并返回执行结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的终端命令",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}

TERMINAL_EXECUTE_BATCH_TOOL = {
    "type": "function",
    "function": {
        "name": "terminal_execute_batch",
        "description": "在当前设备终端按顺序执行多条命令，并返回每条命令的结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "按顺序执行的终端命令列表",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "每条命令的超时时间（秒）",
                },
            },
            "required": ["commands"],
            "additionalProperties": False,
        },
    },
}

TOOL_DEFINITIONS = [TERMINAL_EXECUTE_TOOL, TERMINAL_EXECUTE_BATCH_TOOL]
