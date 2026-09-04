from __future__ import annotations

import asyncio

from device_tui.application.ai.agent import AgentContext, DeviceAgent, AgentEvent
from device_tui.application.ai.llm import LlmResponse, ToolCall
from device_tui.application.ai.llm import LlmClientError, OpenAiCompatibleClient


class FakeLlm:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self.responses = [
            LlmResponse(
                text="我先检查 CPU。",
                tool_calls=[ToolCall("call-1", "terminal_execute", {"command": "display cpu"})],
            ),
            LlmResponse(
                text="我再检查占用最高的进程。",
                tool_calls=[ToolCall("call-2", "terminal_execute", {"command": "display process cpu"})],
            ),
            LlmResponse(text="CPU 高的主要原因已经确认。"),
        ]

    async def chat(self, *, messages: list[dict], tools: list[dict]) -> LlmResponse:
        del tools
        self.calls.append(list(messages))
        return self.responses.pop(0)


class FakeExecutor:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def execute(self, tool_call: ToolCall, context: AgentContext) -> dict:
        self.commands.append(str(tool_call.arguments["command"]))
        context.device_id = context.device_id or "device-1"
        context.session_id = context.session_id or "session-1"
        return {
            "ok": True,
            "status": "completed",
            "device_id": context.device_id,
            "session_id": context.session_id,
            "output": f"{self.commands[-1]} output",
        }


def test_device_agent_loops_until_final_answer_and_keeps_context() -> None:
    llm = FakeLlm()
    executor = FakeExecutor()
    events: list[AgentEvent] = []
    context = AgentContext("conversation-1")

    result = asyncio.run(
        DeviceAgent(llm, executor, event_callback=events.append).run(
            "帮我检查 CPU 为什么很高",
            context,
        )
    )

    assert result == "CPU 高的主要原因已经确认。"
    assert executor.commands == ["display cpu", "display process cpu"]
    assert context.device_id == "device-1"
    assert context.session_id == "session-1"
    assert [event.type for event in events] == [
        "agent.started",
        "agent.tool.started",
        "agent.tool.output",
        "agent.tool.completed",
        "agent.tool.started",
        "agent.tool.output",
        "agent.tool.completed",
        "agent.message",
        "agent.completed",
    ]
    assert any(item.get("role") == "tool" for item in context.messages)


def test_device_agent_enforces_iteration_limit() -> None:
    class EndlessLlm:
        async def chat(self, *, messages: list[dict], tools: list[dict]) -> LlmResponse:
            del messages, tools
            return LlmResponse(tool_calls=[ToolCall("call", "terminal_execute", {"command": "show"})])

    class NoopExecutor:
        async def execute(self, tool_call: ToolCall, context: AgentContext) -> dict:
            del tool_call, context
            return {"ok": True}

    from device_tui.application.ai.agent import AgentIterationLimitError

    try:
        asyncio.run(DeviceAgent(EndlessLlm(), NoopExecutor(), max_iterations=2).run("loop", AgentContext("c")))
    except AgentIterationLimitError:
        pass
    else:
        raise AssertionError("expected AgentIterationLimitError")


def test_openai_compatible_response_parses_text_and_tool_calls() -> None:
    payload = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": "我开始检查。",
                "tool_calls": [{
                    "id": "call-1",
                    "function": {
                        "name": "terminal_execute",
                        "arguments": '{"command":"display cpu"}',
                    },
                }],
            },
        }],
    }
    response = OpenAiCompatibleClient._parse_response(payload)
    assert response.text == "我开始检查。"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].arguments == {"command": "display cpu"}


def test_openai_compatible_response_rejects_invalid_tool_arguments() -> None:
    try:
        OpenAiCompatibleClient._parse_response({
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "function": {"name": "terminal_execute", "arguments": "oops"},
                    }],
                },
            }],
        })
    except LlmClientError:
        pass
    else:
        raise AssertionError("expected LlmClientError")
