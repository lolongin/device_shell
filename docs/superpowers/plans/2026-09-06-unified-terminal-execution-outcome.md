# Unified Terminal Execution Outcome Implementation Plan

1. Add an application-layer prompt and command-outcome classifier with common
   prompt/error rules and deterministic result evidence.
2. Make command-prompt detection exclude confirmation, pagination, and
   credential prompts.
3. Extend the terminal runner with an explicit waiting-for-input phase,
   machine-readable outcomes, per-command batch outcomes, and an attention
   signal that wakes synchronous MCP calls without ending the execution.
4. Expose generation-aware terminal replay snapshots from `SessionHub` and use
   them for safe `fresh` or explicit `attach` interaction starts.
5. Extend MCP tool schemas and terminal-read responses with attachment cursor,
   generation, and prompt metadata.
6. Add unit, runner, lease, attachment, and HTTP MCP regression coverage.
7. Run focused tests, the complete Python suite, TypeScript checks, and the
   production desktop build because the modified MCP schema is consumed by the
   Electron application.
