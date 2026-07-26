# Automatic Controller Detection for Package Upgrades

## Problem

The one-click package-upgrade workflow currently treats the checked
`include_slave` option as proof that the selected device has two controllers.
Because the option is enabled by default, a single-controller device is asked
to read `slave#flash:/`, copy the package there, and set startup software with
`all` or `slave-board`. Those commands fail and stop an otherwise valid
single-controller upgrade.

## Scope

Make one-click upgrades automatically detect whether the configured standby
storage is available and select the single- or dual-controller path for that
run. Preserve the existing manual script-generation behavior and the existing
dual-controller workflow.

## Design

When automatic dual-controller handling is enabled, the precheck continues to
issue `dir <slave_storage>`. The command output is classified as one of:

- available: the output represents a readable directory on the configured
  standby storage;
- absent: the output contains a known device/path-not-present failure;
- indeterminate: the output fails for another reason or cannot be classified.

For `available`, the run keeps `include_slave=True` and follows the existing
copy, verification, and startup `all`/`slave-board` path.

For `absent`, the run creates an effective configuration with
`include_slave=False`. All remaining safety checks, cleanup planning, transfer,
verification, and startup commands use that effective configuration. The UI
reports that no standby controller was detected and that the upgrade is
continuing in single-controller mode.

For `indeterminate`, the precheck stops with the original device error instead
of silently downgrading. This prevents permission, session, or command failures
from being mistaken for a single-controller topology.

The primary-storage precheck remains mandatory and is never eligible for
automatic downgrade.

## UI Behavior

The existing checkbox remains enabled by default but its label describes
automatic dual-controller detection. Clearing it explicitly forces the
single-controller path and skips standby probing, preserving a manual escape
hatch.

The pipeline status identifies whether the run selected single- or
dual-controller mode. Automatic detection changes only the current run; it
does not persistently rewrite device data or global settings.

## Implementation Boundaries

Topology classification belongs in a small pure helper in
`src/package_upgrade.py` so it can be tested independently of PySide6.
`src/app/package_upgrade_ops.py` owns orchestration: it records precheck
outputs, resolves the effective configuration once, updates the run state and
UI, and passes the resolved configuration through the existing execution
pipeline.

No unrelated session, transfer-service, or device-model changes are required.

## Error Handling

Known standby-absent output is non-fatal and triggers single-controller mode.
Authentication failures, timeouts, disconnected sessions, unrecognized CLI
errors, and unreadable primary storage remain fatal. Existing package-size,
free-space, cleanup-safety, transfer, startup, and final confirmation failures
remain unchanged.

## Tests

Add focused tests for:

1. known standby-not-present output selecting single-controller mode;
2. readable standby-directory output retaining dual-controller mode;
3. unknown or permission-related errors remaining fatal;
4. resolved single-controller runs omitting standby copy, verification,
   cleanup, and `all`/`slave-board` startup commands;
5. existing dual-controller behavior remaining unchanged.

Validation also includes the relevant pytest modules and
`python -m py_compile src\*.py`.
