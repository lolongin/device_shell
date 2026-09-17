"""测试 loop.until 的实际执行行为"""
import asyncio
from device_tui.application.workflow_plugins.utility import UntilActivityHandler
from device_tui.framework import ActivityInvocation, ActivityContext, WorkflowRun

async def test_loop_until():
    # 模拟一个简单的子任务执行器
    call_count = 0

    async def mock_child_runner(action_id, inputs, context, report):
        nonlocal call_count
        call_count += 1
        print(f"第 {call_count} 次执行: action_id={action_id}, inputs={inputs}")
        return {
            "status": "succeeded",
            "output": f"execution {call_count}",
            "call_number": call_count
        }

    handler = UntilActivityHandler(mock_child_runner)

    # 创建一个永远不满足的条件（用于测试最大次数）
    invocation = ActivityInvocation(
        activity_id="loop.until",
        invocation_id="test-loop",
        workflow_run_id="test-run",
        inputs={
            "action_id": "terminal.command",
            "action_inputs": {"command": "display version"},
            "condition": "result.call_number > 100",  # 永远不会满足
            "max_iterations": 10,
            "interval_seconds": 0.1
        },
        context={}
    )

    # 创建一个虚拟的 context
    workflow_run = WorkflowRun(
        id="test-run",
        workflow_id="test",
        workflow_version="1",
        device_id="test-device"
    )
    context = ActivityContext(workflow_run, invocation)

    # 执行
    result = await handler.execute(invocation, context, None)

    print(f"\n=== 执行结果 ===")
    print(f"状态: {result.status}")
    print(f"实际调用次数: {call_count}")
    print(f"输出中的 iterations: {result.outputs.get('iterations')}")
    print(f"matched: {result.outputs.get('matched')}")
    print(f"错误: {result.error}")
    print(f"\n所有结果:")
    for i, r in enumerate(result.outputs.get('results', []), 1):
        print(f"  {i}. {r}")

if __name__ == "__main__":
    asyncio.run(test_loop_until())
