# Workflow Framework

The framework in `device_tui.application.workflows` is the generic execution
boundary for network-device workflows. Package replacement is one provider,
not a special case in the runtime.

## Boundaries

`WorkflowRuntime` owns state transitions, event persistence, expectations,
watchdog decisions, reconcile dispatch, checkpoints, and constrained decisions.
`WorkflowProvider` owns business states and policy. `DeviceAdapter` owns vendor
syntax, prompt parsing, capabilities, and read-only device probes.

Credentials, FTP username/password prompts, pagination, SSH host-key prompts,
and Y/N confirmations remain in the interaction layer. They never become a
DecisionPoint.

## Extension points

Register a provider and adapter through the default registries:

```python
from device_tui.application.workflows import (
    build_default_adapter_registry,
    build_default_workflow_registry,
)

workflows = build_default_workflow_registry()
adapters = build_default_adapter_registry()
workflow = workflows.build(
    "network.package_upgrade",
    {"package_ref": "flash:/image.cc", "expected_version": "V8"},
)
adapter = adapters.resolve({"vendor": "Huawei", "platform": "VRP"}, {"huawei.vrp"})
```

Actions are registered by namespaced operation, for example
`device.probe`, `file.transfer`, or `device.reboot`. A handler emits semantic
events; it must not report success merely because a command was written.

## Recovery contract

An Action with unmet expectations is marked `unknown` and is reconciled before
retry or failure. Reconcile results are classified as:

```text
confirmed_success
confirmed_not_started
confirmed_in_progress
confirmed_failed
indeterminate
```

Only the first four can be handled by deterministic Workflow policy. The last
classification creates a DecisionPoint with explicitly declared Options.

## Huawei package provider

`HuaweiVrpPackageUpgradeProvider` declares the following states:

```text
precheck → ftp_login → transfer → verify_package → configure_startup
          → reboot → wait_online → verify_version → complete
```

It also declares a rollback state. The provider requires the Huawei VRP,
file-transfer, and reboot capabilities. It does not contain Huawei CLI
strings; those belong to `HuaweiVrpWorkflowAdapter` and the existing upgrade
driver.

## API

The legacy task API remains available. Framework discovery and preview are
available at:

```text
GET  /api/v1/framework/workflows
POST /api/v1/framework/workflows/{workflow_id}/preview
```

The legacy `device_upgrade` task id is a compatibility name only. Its
execution is always compiled to `network.package_upgrade` and driven by
`WorkflowRuntime`; the old `WorkflowEngine` is not an upgrade executor. The
legacy Task and Operation records are projections for existing clients.

The old task engine remains available only for non-Framework workflows and
legacy Agent plans while those callers are migrated. New device workflows
must register a Framework provider and action handlers instead of adding a
special branch to `TaskManager`.

Execution handlers are deliberately registered by the application composition
root. A caller must not bypass the existing session, credential, operation,
and device-lease services to execute an Action.
