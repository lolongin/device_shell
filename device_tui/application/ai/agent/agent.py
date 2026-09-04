"""LLM-driven device operation loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from device_tui.application.ai.llm.client import LlmClient
from device_tui.application.ai.llm.models import LlmResponse, ToolCall

from .context import AgentContext
from .events import AgentEvent
from .executor import AgentToolExecutor
from .tools import TOOL_DEFINITIONS


SYSTEM_PROMPT = """你是 device_shell 的设备操作 Agent。

你的任务是帮助用户观察、诊断和操作当前设备。

工作原则：
1. 先理解用户目标。
2. 不确定时先观察设备状态。
3. 可以连续调用多个工具。
4. 每次工具返回结果后重新判断下一步。
5. 不要假设命令执行成功，必须根据返回结果判断。
6. 对复杂问题进行逐步诊断。
7. 完成操作后验证结果。
8. 最终用简洁自然语言总结做了什么、发现了什么、结果如何。

当前设备和 session 信息由运行时 Context 提供。
"""


class AgentIterationLimitError(RuntimeError):
    pass


class DeviceAgent:
    def __init__(
        self,
        llm: LlmClient,
        executor: AgentToolExecutor,
        *,
        max_iterations: int = 30,
        event_callback: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        self._llm = llm
        self._executor = executor
        self._max_iterations = max(1, int(max_iterations))
        self._event_callback = event_callback

    async def run(self, user_message: str, context: AgentContext) -> str:
        message = user_message.strip()
        if not message:
            raise ValueError("user_message is required")
        self._ensure_system_message(context)
        context.messages.append({"role": "user", "content": message})
        self._emit("agent.started", {"conversation_id": context.conversation_id, "message": message})
        try:
            for iteration in range(self._max_iterations):
                response = await self._llm.chat(
                    messages=context.messages,
                    tools=TOOL_DEFINITIONS,
                )
                if not response.tool_calls:
                    text = response.text.strip()
                    context.messages.append({"role": "assistant", "content": text})
                    self._emit("agent.message", {"content": text, "iteration": iteration})
                    self._emit("agent.completed", {"content": text, "iterations": iteration + 1})
                    return text
                self._append_assistant_tool_calls(context, response)
                for call in response.tool_calls:
                    self._emit(
                        "agent.tool.started",
                        {"tool": call.name, "tool_call_id": call.id, "arguments": call.arguments},
                    )
                    result = await self._executor.execute(call, context)
                    self._emit(
                        "agent.tool.output",
                        {"tool": call.name, "tool_call_id": call.id, "output": result},
                    )
                    context.messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                    self._emit(
                        "agent.tool.completed",
                        {"tool": call.name, "tool_call_id": call.id, "ok": bool(result.get("ok"))},
                    )
            raise AgentIterationLimitError(
                f"Agent exceeded the maximum of {self._max_iterations} iterations"
            )
        except Exception as exc:
            self._emit("agent.error", {"error": str(exc)})
            raise

    @staticmethod
    def _ensure_system_message(context: AgentContext) -> None:
        if not context.messages or context.messages[0].get("role") != "system":
            context.messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

    @staticmethod
    def _append_assistant_tool_calls(context: AgentContext, response: LlmResponse) -> None:
        context.messages.append({
            "role": "assistant",
            "content": response.text or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in response.tool_calls
            ],
        })

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._event_callback is not None:
            self._event_callback(AgentEvent(event_type, data))

