"""Async local process adapter for build and test Activities."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ProcessExecutionResult:
    status: str
    returncode: int | None
    output: str
    timed_out: bool = False
    cancelled: bool = False


class LocalProcessAdapter:
    """Run a local executable without involving the workflow runtime."""

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def run(
        self,
        invocation_id: str,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float = 3_600,
        max_output_chars: int = 1_048_576,
        on_output: Callable[[str], None] | None = None,
    ) -> ProcessExecutionResult:
        command = tuple(str(item) for item in argv if str(item))
        if not command:
            raise ValueError("process argv is required")
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(Path(cwd).resolve()) if cwd else None,
            env=dict(env) if env is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._processes[invocation_id] = process
        chunks: list[str] = []
        try:
            async def collect() -> None:
                assert process.stdout is not None
                while True:
                    chunk = await process.stdout.read(16_384)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    chunks.append(text)
                    if sum(len(item) for item in chunks) > max_output_chars:
                        joined = "".join(chunks)
                        chunks[:] = [joined[-max_output_chars:]]
                    if on_output is not None:
                        on_output(text)
                await process.wait()

            await asyncio.wait_for(collect(), timeout=max(0.01, timeout_seconds))
            return ProcessExecutionResult(
                status="succeeded" if process.returncode == 0 else "failed",
                returncode=process.returncode,
                output="".join(chunks),
            )
        except asyncio.TimeoutError:
            await self.cancel(invocation_id)
            return ProcessExecutionResult("unknown", process.returncode, "".join(chunks), timed_out=True)
        except asyncio.CancelledError:
            await self.cancel(invocation_id)
            return ProcessExecutionResult("cancelled", process.returncode, "".join(chunks), cancelled=True)
        finally:
            self._processes.pop(invocation_id, None)

    async def cancel(self, invocation_id: str) -> None:
        process = self._processes.get(invocation_id)
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


__all__ = ["LocalProcessAdapter", "ProcessExecutionResult"]
