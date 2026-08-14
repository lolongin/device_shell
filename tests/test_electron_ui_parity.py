from pathlib import Path


APP_VUE = Path("desktop/src/renderer/src/App.vue")
STYLES_CSS = Path("desktop/src/renderer/src/styles.css")
TERMINAL_PANE = Path("desktop/src/renderer/src/components/TerminalPane.vue")
TERMINAL_SPLIT_WORKSPACE = Path("desktop/src/renderer/src/components/TerminalSplitWorkspace.vue")
TERMINAL_QUICK_TOOLBAR = Path(
    "desktop/src/renderer/src/components/TerminalQuickToolbar.vue"
)
SESSION_MANAGER = Path("desktop/src/renderer/src/components/SessionManager.vue")
SESSION_STATUS = Path("desktop/src/renderer/src/sessionStatus.ts")
CONTEXT_MENU = Path("desktop/src/renderer/src/contextMenu.ts")
COMMAND_WORKSPACE = Path("desktop/src/renderer/src/components/CommandWorkspace.vue")
AUTOMATION_WORKSPACE = Path("desktop/src/renderer/src/components/AutomationWorkspace.vue")
AUTOMATION_STEP_EDITOR = Path(
    "desktop/src/renderer/src/components/AutomationStepEditor.vue"
)
AUTOMATION_ACTION_LIST = Path(
    "desktop/src/renderer/src/components/AutomationActionList.vue"
)
UPGRADE_WORKSPACE = Path("desktop/src/renderer/src/components/UpgradeWorkspace.vue")
SETTINGS_PANEL = Path("desktop/src/renderer/src/components/SettingsPanel.vue")
HELP_PANEL = Path("desktop/src/renderer/src/components/HelpPanel.vue")
PROFILE_DIALOG = Path("desktop/src/renderer/src/components/ConnectionProfileDialog.vue")
GROUP_DIALOG = Path("desktop/src/renderer/src/components/ConnectionGroupDialog.vue")
DIALOG_FOCUS = Path("desktop/src/renderer/src/composables/useDialogFocus.ts")
WORKSPACE_STORE = Path("desktop/src/renderer/src/stores/workspace.ts")
TYPES_TS = Path("desktop/src/renderer/src/types.ts")
MAIN_TS = Path("desktop/src/main/index.ts")
PACKAGE_JSON = Path("desktop/package.json")
UI_PARITY_SMOKE = Path("desktop/scripts/smoke-ui-parity.mjs")
PRELOAD_TS = Path("desktop/src/preload/index.ts")


def test_electron_terminal_quick_toolbar_keeps_persistent_send_workflow() -> None:
    toolbar = TERMINAL_QUICK_TOOLBAR.read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    transport = Path("desktop/src/renderer/src/transport/api.ts").read_text(
        encoding="utf-8"
    )

    for label in (
        "新增快捷发送",
        "敏感内容",
        "发送后追加 Enter",
        "替换敏感内容",
    ):
        assert label in toolbar

    assert 'data-testid="terminal-quick-toolbar"' in toolbar
    assert ':data-quick-send-id="button.id"' in toolbar
    assert 'data-testid="quick-send-add"' in toolbar
    assert 'data-testid="quick-send-name"' in toolbar
    assert 'data-testid="quick-send-response"' in toolbar
    assert 'data-testid="quick-send-save"' in toolbar
    assert "workspace.sendQuickSendButton(button.id)" in toolbar
    assert "device-tui.desktop-v2.quick-toolbar-collapsed" in toolbar
    assert ':aria-label="`编辑 ${button.name}`"' in toolbar

    assert "quickSendButtons" in store
    assert "saveQuickSendButton" in store
    assert "deleteQuickSendButton" in store
    assert "sendQuickSendButton" in store
    assert "/api/v1/automation/quick-send-buttons" in transport


def test_electron_activity_rail_does_not_expose_ai_tab() -> None:
    app = APP_VUE.read_text(encoding="utf-8")

    assert "import AiWorkspace" not in app
    assert "<AiWorkspace" not in app
    assert "toggleAiPanel" not in app
    assert 'title="AI助手"' not in app
    assert "<Bot" not in app


def test_electron_side_layout_uses_hierarchical_session_manager() -> None:
    manager = SESSION_MANAGER.read_text(encoding="utf-8")
    app = APP_VUE.read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    for label in (
        "会话管理器",
        "搜索设备、会话",
        "全部展开",
        "全部收起",
        "调整会话管理器宽度",
    ):
        assert label in manager

    assert "new Map<string, SessionSummary[]>()" in manager
    assert "session.device_id" in manager
    assert "visibleGroups" in manager
    assert 'role="tree"' in manager
    assert 'role="treeitem"' in manager
    assert ':data-device-group-id="group.id"' in manager
    assert "device-tui.desktop-v2.session-manager-width" in manager
    assert "device-tui.desktop-v2.session-manager-collapsed-groups" in manager
    assert "Math.max(200, Math.min(480" in manager
    assert "rect.right - event.clientX" in manager
    assert "event.key === 'ArrowLeft' ? 10 : -10" in manager
    assert "application/x-device-tui-session" in manager
    assert "emit('deviceContext'" in manager
    assert "emit('sessionContext'" in manager

    assert "import SessionManager" in app
    assert "<SessionManager" in app
    assert 'class="session-sidebar"' in app
    assert 'aria-label="右侧会话栏"' in app
    assert '!document.querySelector(\'.session-workspace .session-manager\')' in MAIN_TS.read_text(encoding="utf-8")
    assert "sessionManagerDeviceContextMenu" in app
    for label in (
        "关闭当前设备会话",
        "关闭左侧设备会话",
        "关闭右侧设备会话",
        "关闭其他设备会话",
        "关闭所有设备会话",
        "定位到设备列表",
        "打开设备管理口",
        "打开 Linux 后台",
        "打开串口",
        "占用设备",
        "释放设备",
        "设备掉电",
    ):
        assert label in app

    assert "function closeDeviceSessionGroups(" in store
    assert "new Set(snapshot.map((session) => session.device_id))" in store
    assert ".session-manager-tree" in styles
    assert ".session-manager-resize-handle" in styles
    assert "grid-template-rows: auto auto auto minmax(0, 1fr);" in styles
    smoke = MAIN_TS.read_text(encoding="utf-8")
    for check in (
        "hierarchicalSessionManagerGroupsSessionsByDevice",
        "sessionManagerSearchFiltersDevicesAndSessions",
        "sessionManagerDeviceContextActions",
        "sessionManagerWidthResizePersists",
        "sessionManagerTreeStartsBelowSearch",
        "sessionManagerGroupCollapseStatePersists",
        "sessionManagerWidthRestored",
        "sessionManagerGroupStateRestored",
        "sessionManagerLivesInRightSidebar",
    ):
        assert check in smoke


def test_electron_advanced_automation_editor_covers_python_action_model() -> None:
    workspace = AUTOMATION_WORKSPACE.read_text(encoding="utf-8")
    assert "runActionHint" in workspace
    assert "activeSessionConnected" in workspace
    assert "automation-rule-count" in workspace
    steps = AUTOMATION_STEP_EDITOR.read_text(encoding="utf-8")
    actions = AUTOMATION_ACTION_LIST.read_text(encoding="utf-8")
    types = TYPES_TS.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    for label in ("基础响应", "分步流程", "动作流"):
        assert label in workspace
    assert "automationTargets" in workspace
    assert "session-id:${session.id}" in workspace
    assert "timeout_ms" in types
    assert "automation-step-timeout" in steps
    assert "等待超时（ms，0=不限）" in steps
    assert "let pendingSteps: AutoResponseStep[] | null = null" in steps
    assert "function commitSteps" in steps
    assert "pendingSteps || props.steps" in steps
    assert "let pendingActions: AutoResponseAction[] | null = null" in actions
    assert "function commitActions" in actions
    assert "pendingActions || props.actions" in actions
    assert "normalizeSteps" in workspace
    assert "normalizeActions" in workspace
    assert "validateActions" in workspace
    assert "protectedAdvancedStructure" in workspace
    assert "<AutomationStepEditor" in workspace
    assert "<AutomationActionList" in workspace

    for field in (
        "response_targets",
        "response_delays",
        "response_append_enters",
    ):
        assert field in steps
        assert field in types
    for label in (
        "添加步骤",
        "添加响应",
        "发送目标",
        "发送前延迟（ms）",
        "发送后追加 Enter",
    ):
        assert label in steps

    for kind in ("send", "wait", "loop", "condition", "exit"):
        assert f'data-action-kind="{kind}"' in actions
    for label in (
        "执行次数（0=持续循环）",
        "每轮间隔（ms）",
        "条件文本",
        "条件匹配",
        "退出范围",
        "退出当前循环",
        "停止整个规则",
    ):
        assert label in actions
    for field in (
        "repeat_count",
        "interval_ms",
        "condition_pattern",
        "condition_match_type",
        "exit_pattern",
        "exit_scope",
    ):
        assert field in actions
        assert field in types

    assert "AutomationActionList" in actions
    assert 'data-action-kind="set"' in actions
    assert "变量名" in actions
    assert "变量值" in actions
    assert "{{loop.index}}" in actions
    assert "variable_operation" in workspace
    assert "variable_name" in types
    assert "const expandedIndexes" in actions
    assert "expandedIndexes.value = new Set([next.length - 1])" in actions
    assert ": new Set([index])" in actions
    assert "function actionSummary" in actions
    assert "function actionMeta" in actions
    assert ':aria-expanded="isExpanded(index)"' in actions
    assert 'v-show="isExpanded(index)"' in actions
    assert "点击动作展开参数" in actions
    assert ".automation-action-summary" in styles
    assert ".automation-action-details" in styles
    assert ".automation-step-editor" in styles
    assert ".automation-action-card.kind-loop" in styles
    assert ".automation-action-card.kind-condition" in styles
    assert ".automation-action-card.kind-exit" in styles
    smoke = MAIN_TS.read_text(encoding="utf-8")
    assert "advancedAutomationStepEditorPersistsAndRuns" in smoke
    assert "advancedAutomationActionEditorPersistsNestedFlow" in smoke
    assert "automationModeSwitchPreservesDraftWithoutDialog" in smoke
    assert "automationLivePreviewTracksDraftWithoutDispatch" in smoke
    assert 'data-testid="automation-preview"' in workspace
    assert 'data-testid="automation-live-preview"' in workspace
    assert "schedulePreview" in workspace
    assert "previewGeneration" in workspace
    assert "desktopApi.previewAutomationRule" in workspace
    assert "automation-preview-panel" not in workspace
    assert ".automation-live-preview" in styles
    assert ".automation-preview-steps" in styles
    assert "切换编辑模式会将现有高级结构转换" not in workspace
    assert "cachedSteps" in workspace
    assert "cachedActions" in workspace


def test_terminal_automation_is_a_non_modal_current_session_sidebar() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    automation = AUTOMATION_WORKSPACE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")

    assert "workspace.automationPanelOpen || workspace.transferPanelOpen" in app
    assert 'class="automation-workspace"' in automation
    assert 'role="region"' in automation
    assert ':data-active-session-id="workspace.activeSessionId"' in automation
    assert 'aria-modal="true"' not in automation
    backdrop_start = styles.index("\n.automation-backdrop {") + 1
    backdrop = styles[backdrop_start:styles.index(".automation-workspace", backdrop_start)]
    assert "position: fixed" not in backdrop
    assert ".navigator, .automation-backdrop, .transfer-backdrop, .upgrade-backdrop { grid-column: 2;" in styles
    assert ".automation-body { min-height: 0; display: grid; grid-template-rows:" in styles
    assert ".automation-rule-list" in styles
    assert "overflow-x: auto" in styles
    assert "terminalAutomationKeepsTerminalVisibleAndInteractive" in main
    assert "leftOperationWorkbenchWidthResizePersists" in main


def test_electron_file_service_exposes_safe_log_and_client_hint() -> None:
    transfer = Path(
        "desktop/src/renderer/src/components/TransferWorkspace.vue"
    ).read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    transport = Path("desktop/src/renderer/src/transport/api.ts").read_text(
        encoding="utf-8"
    )
    styles = STYLES_CSS.read_text(encoding="utf-8")

    for label in (
        "设备侧客户端命令",
        "复制客户端命令",
        "文件服务运行日志",
        "刷新服务日志",
        "复制服务日志",
        "清空服务日志",
    ):
        assert label in transfer
    assert "workspace.transferClientCommand" in transfer
    assert "workspace.transferServiceLog.join('\\n')" in transfer
    assert "navigator.clipboard.writeText" in transfer
    assert 'data-testid="transfer-service-log"' in transfer
    assert 'data-testid="transfer-client-command"' in transfer

    assert "transferServiceLog" in store
    assert "transferClientCommand" in store
    assert "event.type === 'transfer.service.log'" in store
    assert "loadTransferServiceLog" in store
    assert "clearTransferServiceLog" in store
    assert "/api/v1/file-transfer/service/log" in transport
    assert ".transfer-service-log-card" in styles
    assert ".transfer-client-hint" in styles
    smoke = MAIN_TS.read_text(encoding="utf-8")
    assert "fileServiceLogAndClientCommandAreVisibleAndSafe" in smoke
    assert "fileServiceLogClearPersistsThroughPythonService" in smoke


def test_managed_transfer_and_package_upgrade_keep_terminal_visible() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    transfer = Path("desktop/src/renderer/src/components/TransferWorkspace.vue").read_text(encoding="utf-8")
    upgrade = UPGRADE_WORKSPACE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")

    assert "operationPanelOpen" in app
    assert "showSessionSidebar" in app
    assert 'v-show="!operationPanelOpen" class="navigator"' in app
    assert 'data-testid="operation-panel-resize-handle"' in app
    assert 'role="region"' in transfer
    assert 'aria-modal="true"' not in transfer
    assert "transferActionHint" in transfer
    assert "activeSessionConnected" in transfer
    assert 'role="region"' in upgrade
    assert 'aria-modal="true"' not in upgrade
    assert "upgradeActionHint" in upgrade
    assert "terminal session is not connected" in upgrade
    assert ".operation-readiness" in styles
    assert ".navigator, .automation-backdrop, .transfer-backdrop, .upgrade-backdrop { grid-column: 2;" in styles
    assert ".workspace-stage { grid-column: 3;" in styles
    assert ".session-sidebar { grid-column: 4;" in styles
    transfer_start = styles.index("\n.transfer-backdrop {") + 1
    upgrade_start = styles.index("\n.upgrade-backdrop {") + 1
    transfer_backdrop = styles[transfer_start:styles.index(".transfer-workspace", transfer_start)]
    upgrade_backdrop = styles[upgrade_start:styles.index(".upgrade-workspace", upgrade_start)]
    assert "position: fixed" not in transfer_backdrop
    assert "position: fixed" not in upgrade_backdrop
    assert "managedTransferKeepsTerminalVisibleAndInteractive" in main
    assert "managedTransferCardsRemainVisibleAndOrdered" in main
    assert "packageUpgradeKeepsTerminalVisibleAndInteractive" in main
    assert "packageUpgradeCardsRemainVisibleAndOrdered" in main
    assert "overflow-x: auto" in styles[styles.index(".upgrade-stage-list {"):styles.index(".upgrade-stage-list > div {")]
    terminal_pane = Path("desktop/src/renderer/src/components/TerminalPane.vue").read_text(encoding="utf-8")
    assert ':data-session-id="session.id"' in terminal_pane


def test_terminal_toolbar_exposes_current_session_operations_without_navigation() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    pane = TERMINAL_PANE.read_text(encoding="utf-8")
    split = TERMINAL_SPLIT_WORKSPACE.read_text(encoding="utf-8")
    manager = SESSION_MANAGER.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert 'title="托管传输当前设备"' in pane
    assert 'title="升级当前设备系统包"' in pane
    assert 'title="当前会话与设备操作"' in pane
    assert "transfer: [sessionId: string]" in pane
    assert "upgrade: [sessionId: string]" in pane
    assert "context: [sessionId: string, event: MouseEvent]" in pane
    assert '@transfer="emit(\'transfer\', $event)"' in split
    assert '@upgrade="emit(\'upgrade\', $event)"' in split
    assert '@context="(sessionId, event) => emit(\'context\', sessionId, event)"' in split
    assert "function openSessionTransfer(sessionId: string)" in app
    assert "function openSessionUpgrade(sessionId: string)" in app
    assert "function openSessionToolbarContext(sessionId: string, event: MouseEvent)" in app
    assert ".terminal-operation-button" in styles


def test_transfer_workspace_polls_service_log_while_open() -> None:
    transfer = Path(
        "desktop/src/renderer/src/components/TransferWorkspace.vue"
    ).read_text(encoding="utf-8")

    assert "pollingTimer = setInterval" in transfer
    assert "void workspace.refreshOperations()" in transfer
    assert "void workspace.loadTransferServiceLog()" in transfer


def test_electron_package_upgrade_has_python_owned_manual_fallback() -> None:
    upgrade = UPGRADE_WORKSPACE.read_text(encoding="utf-8")
    transport = Path("desktop/src/renderer/src/transport/api.ts").read_text(
        encoding="utf-8"
    )
    styles = STYLES_CSS.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")

    for label in (
        "手动脚本兜底",
        "读取当前终端",
        "生成脚本",
        "复制脚本",
        "发送脚本",
        "已检查脚本与目标终端",
        "密码不会进入界面",
    ):
        assert label in upgrade
    for test_id in (
        "upgrade-manual-fallback",
        "upgrade-manual-terminal",
        "upgrade-manual-script",
        "upgrade-manual-read",
        "upgrade-manual-generate",
        "upgrade-manual-copy",
        "upgrade-manual-confirm",
        "upgrade-manual-send",
    ):
        assert f'data-testid="{test_id}"' in upgrade
    assert "{{file_transfer.password}}" in upgrade
    assert "navigator.clipboard.writeText(manualScript.value)" in upgrade
    assert "desktopApi.packageUpgradeManualTerminal" in upgrade
    assert "desktopApi.generatePackageUpgradeManualPlan" in upgrade
    assert "desktopApi.sendPackageUpgradeManualScript" in upgrade
    assert "/api/v1/package-upgrades/manual/plan" in transport
    assert "/api/v1/package-upgrades/manual/send" in transport
    assert ".upgrade-manual-field textarea:focus" in styles
    assert "packageUpgradeManualFallbackReadsGeneratesEditsCopiesAndSends" in main
    assert "DEVICE_TUI_CAPTURE_MANUAL_UPGRADE_PATH" in main


def test_electron_device_list_keeps_legacy_table_columns() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    for label in ("序号", "设备", "板类型", "CPU", "Slot", "状态"):
        assert label in app

    assert 'class="device-list device-table-list"' in app
    assert 'class="device-table-header"' in app
    assert 'class="device-row device-table-row"' in app
    assert "device.device_type" in app
    assert "device.cpu" in app
    assert "device.board_type" in app
    assert "device.slot" in app
    assert "device.status_text" in app
    assert "device.tooltip" in app
    assert ".device-table-row" in styles
    assert "grid-template-columns: 52px var(--navigator-width, 500px) minmax(520px, 1fr);" in styles
    assert ".app-shell.has-session-sidebar" in styles
    assert "legacyDeviceColumnsFitWithoutHorizontalScroll" in MAIN_TS.read_text(encoding="utf-8")


def test_electron_device_search_covers_legacy_hidden_table_fields() -> None:
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    types = TYPES_TS.read_text(encoding="utf-8")

    for field in ("row_id", "board_id", "board_type", "slot", "status_text", "tooltip"):
        assert f"{field}: string" in types
        assert f"device.{field}" in store


def test_electron_device_filters_keep_selection_valid_and_show_mine_count() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    types = TYPES_TS.read_text(encoding="utf-8")

    assert "const myOccupancyCount = computed" in store
    assert "owned_device_ids: string[]" in types
    assert "ownedDeviceIds.value = deviceResponse.owned_device_ids" in store
    assert "ownedDeviceIds.value.includes(device.id)" in store
    assert "ownedDeviceIds.value.length" in store
    assert "workspace.myOccupancyCount" in app
    assert "workspace.filteredDevices.length" in app
    assert "for (const device of workspace.filteredDevices)" in app
    assert "statusCounts.pipeline" in app
    assert "statusCounts.other" in app
    assert "counts[statusKind(device.status)] += 1" in app
    assert app.index("value.includes('流水')") < app.index("value.includes('占用')")
    assert "流水线" in app
    assert "其他" in app
    assert "watch(filteredDevices" in store
    assert "selectedDeviceRowId.value = ''" in store
    assert "selectedDeviceRowId.value = visibleDevices[0].row_id" in store
    assert ".summary-row .pipeline b" in styles
    assert ".summary-row .other b" in styles
    assert 'class="navigator-empty-state device-table-empty"' in app
    assert ":role=\"workspace.filteredDevices.length ? 'table' : 'region'\"" in app
    assert '@click="workspace.clearDeviceFilters"' in app
    assert ".navigator-empty-state" in styles


def test_electron_connection_actions_use_backend_parity_rules() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    types = TYPES_TS.read_text(encoding="utf-8")

    for field in (
        "can_connect_telnet",
        "can_connect_ssh",
        "can_connect_serial",
        "can_claim",
        "can_release",
        "can_power_off",
        "serial_display",
    ):
        assert field in types

    assert "connectionDisabledReason" in app
    assert "function recommendedSessionKind" in app
    assert "function openRecommendedDeviceSession" in app
    assert "recommendedDeviceSessionKind" in app
    assert 'class="empty-workspace-context"' in app
    assert "availableDeviceProtocolLabels" in app
    assert "workspace.openSimulatedSession" not in app[app.index('<section v-else class="empty-workspace">'):]
    assert "device.can_connect_ssh" in app
    assert "device.can_connect_telnet" in app
    assert "device.can_connect_serial" in app
    assert "workspace.selectedDevice.serial_display" in app
    assert "workspace.selectedDevice.can_power_off" in app
    assert "workspace.selectedDevice.can_claim" in app
    assert "workspace.selectedDevice.can_release" in app

    assert "!device?.can_connect_ssh" in store
    assert "!device?.can_connect_telnet" in store
    assert "!device?.can_connect_serial" in store
    assert ".empty-workspace-context" in STYLES_CSS.read_text(encoding="utf-8")


def test_electron_session_creation_deduplicates_rest_and_realtime_results() -> None:
    store = WORKSPACE_STORE.read_text(encoding="utf-8")

    assert "function upsertSession(session: SessionSummary)" in store
    assert "sessions.value.findIndex((item) => item.id === session.id)" in store
    assert "Number(session.sequence || 0) < Number(current.sequence || 0)" in store
    assert "for (const session of sessionResponse) upsertSession(session)" in store
    assert store.count("upsertSession(session)") >= 4


def test_electron_simulated_session_always_targets_canonical_simulator() -> None:
    store = WORKSPACE_STORE.read_text(encoding="utf-8")

    assert "kind === 'simulated'" in store
    assert "devices.value.find((candidate) => candidate.is_simulated)" in store
    assert "desktopApi.createSession(device.id, kind)" in store
    assert "desktopApi.createSession(selectedDeviceId.value, kind)" not in store


def test_ui_smoke_keeps_primary_capture_outside_backend_recovery_transition() -> None:
    main = MAIN_TS.read_text(encoding="utf-8")

    primary_capture = main.index("const primaryImage = await mainWindow.webContents.capturePage()")
    recovery_probe = main.index("backend.crashForRecoveryProbe()")
    assert primary_capture < recovery_probe
    assert "primaryCaptureWritten = true" in main
    assert "stableRecoveryDom" in main
    assert "stableRecoveryDom.loading === false" in main


def test_electron_terminal_supports_split_context_actions_and_drag_drop() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    split = TERMINAL_SPLIT_WORKSPACE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    for direction in ("left", "right", "top", "bottom"):
        assert f"分屏到{'左侧' if direction == 'left' else '右侧' if direction == 'right' else '上方' if direction == 'top' else '下方'}" in app
        assert f"'{direction}'" in split
    assert 'draggable="true"' in app
    assert '@dragstart="startSessionTabDrag($event, session)"' in app
    assert "application/x-device-tui-session" in split
    assert "@dragover=\"handleDragOver($event, pane)\"" in split
    assert "@drop=\"handleDrop($event, pane)\"" in split
    assert "device-tui.desktop-v2.terminal-split-layout" in split
    assert 'role="separator"' in split
    assert 'aria-valuemin="20"' in split
    assert '@pointerdown="startSplitResize"' in split
    assert '@keydown="handleSplitResizeKeydown"' in split
    assert "desktopApi.createSession" not in split
    assert 'data-split-direction="splitDirection || \'none\'"' in split
    assert '.terminal-split-layout[data-split-direction="left"]' in styles
    assert '.terminal-split-layout[data-split-direction="top"]' in styles


def test_electron_device_table_keeps_keyboard_navigation() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert 'tabindex="0"' in app
    assert '@keydown="handleDeviceTableKeydown"' in app
    assert "function handleDeviceListKeydown" in app
    assert "function handleDeviceTableKeydown" in app
    for key in ("ArrowDown", "ArrowUp", "Home", "End", "Enter"):
        assert key in app
    assert "workspace.openSimulatedSession()" in app
    assert ':key="device.row_id"' in app
    assert ':data-device-row-id="device.row_id"' in app
    assert "device.row_id === workspace.selectedDeviceRowId" in app
    assert "device.board_id || index + 1" in app
    assert ".device-table-list:focus-visible" in styles


def test_electron_device_table_keeps_legacy_context_menu_actions() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "const deviceContextMenu = ref" in app
    assert "function openDeviceContextMenu" in app
    assert "function handleDeviceContextKeydown" in app
    assert "event.key === 'ContextMenu'" in app
    assert "event.shiftKey && event.key === 'F10'" in app
    assert '@contextmenu.prevent="openDeviceContextMenu($event, device)"' in app
    assert 'role="menu"' in app
    assert 'role="menuitem"' in app

    for label in (
        "复制设备行",
        "复制 SSH IP",
        "复制 Telnet IP",
        "复制串口 IP",
        "复制连接信息",
        "占用",
        "释放",
        "掉电",
        "打开设备管理口",
        "打开 Linux 后台",
        "打开串口",
    ):
        assert label in app

    assert "deviceRowCopyText" in app
    assert "deviceConnectionCopyText" in app
    assert "function endpointHost" in app
    assert "endpointHost(deviceContextMenu.device.ssh_endpoint)" in app
    assert "endpointHost(deviceContextMenu.device.telnet_endpoint)" in app
    assert "navigator.clipboard.writeText(text)" in app
    assert "workspace.runDeviceAction('claim')" in app
    assert "workspace.runDeviceAction('release')" in app
    assert "workspace.runDeviceAction('power_off')" in app
    assert "openDeviceContextSession('ssh')" in app
    assert "openDeviceContextSession('telnet')" in app
    assert "openDeviceContextSession('serial')" in app
    assert ".device-context-menu" in styles
    assert ".device-context-menu button:disabled" in styles
    assert ".device-context-menu button:focus-visible" in styles


def test_electron_device_inspector_keeps_field_copy_shortcuts() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "function openDeviceInspectorContextMenu" in app
    assert "function handleDeviceInspectorKeydown" in app
    assert "function copyDeviceInspectorField" in app
    assert "function visibleDeviceFieldValue" in app
    assert '@contextmenu.prevent="openDeviceInspectorContextMenu($event, workspace.selectedDevice)"' in app
    assert '@keydown="handleDeviceInspectorKeydown($event, workspace.selectedDevice)"' in app
    assert 'class="property-list copyable-property-list"' in app
    assert 'title="右键打开设备快捷操作"' in app

    for label in (
        "复制状态",
        "复制占用人",
        "复制设备ID",
        "复制板类型",
        "复制区域",
        "复制位置",
        "复制CPU",
        "复制版本",
        "复制 SSH",
        "复制 Telnet",
        "复制串口",
    ):
        assert label in app

    assert "copyDeviceInspectorField('SSH'" in app
    assert "copyDeviceInspectorField('Telnet'" in app
    assert "copyDeviceInspectorField('串口'" in app
    assert "workspace.selectedDevice.serial_display || workspace.selectedDevice.serial_endpoint" in app
    assert ".copyable-property-list" in styles
    assert ".property-copy-button" in styles
    assert ".copyable-property-list:focus-visible" in styles


def test_electron_renderer_restores_persisted_theme_toggle() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "device-tui.desktop-v2.theme" in app
    assert "toggleTheme" in app
    assert "applyRendererTheme" in app
    assert "document.documentElement.dataset.theme" in app
    assert "切换浅色主题" in app
    assert "切换深色主题" in app

    assert ':root[data-theme="light"]' in styles
    assert "color-scheme: light" in styles
    assert '.command-workspace {' in styles
    assert 'background: var(--surface);' in styles
    assert ':root[data-theme="light"] .system-banner' in styles
    assert ':root[data-theme="light"] .notice-banner' in styles
    assert ':root[data-theme="light"] .status-pill[data-status="occupied"]' in styles


def test_electron_restores_persisted_always_on_top_toggle() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")
    preload = PRELOAD_TS.read_text(encoding="utf-8")

    assert "device-tui.desktop-v2.always-on-top" in app
    assert "always-on-top-toggle" in app
    assert "窗口置顶" in app
    assert "取消窗口置顶" in app
    assert "window.desktopApi.setAlwaysOnTop(enabled)" in app
    assert "window:set-always-on-top" in main
    assert "mainWindow.setAlwaysOnTop(enabled)" in main
    assert "ipcRenderer.invoke('window:set-always-on-top', enabled)" in preload


def test_electron_terminal_follows_renderer_theme() -> None:
    terminal = TERMINAL_PANE.read_text(encoding="utf-8")

    assert "readThemeMode" in terminal
    assert "terminalThemeFor" in terminal
    assert "MutationObserver" in terminal
    assert "attributeFilter: ['data-theme']" in terminal
    assert "terminal.options.theme" in terminal
    assert "background: '#f8fafc'" in terminal


def test_electron_terminal_keeps_reconnect_and_disconnect_parity() -> None:
    terminal = TERMINAL_PANE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "const canReconnect = computed" in terminal
    assert "const canDisconnect = computed" in terminal
    assert "watch(() => props.session.status" in terminal
    assert "reconnecting.value" in terminal
    assert "disconnecting.value" in terminal
    assert "会话已断开，按 Enter 可重连" in terminal
    assert "data === '\\r' || data === '\\n'" in terminal
    assert "void reconnect()" in terminal
    assert ":disabled=\"!canDisconnect\"" in terminal
    assert ":disabled=\"!canReconnect\"" in terminal
    assert "[重连失败]" in terminal
    assert "[断开失败]" in terminal
    assert ".icon-button:disabled" in styles


def test_electron_terminal_keeps_legacy_context_menu_actions() -> None:
    terminal = TERMINAL_PANE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "const contextMenu = ref" in terminal
    assert "function openContextMenu" in terminal
    assert "function handleTerminalContextKeydown" in terminal
    assert "event.key === 'ContextMenu'" in terminal
    assert "event.shiftKey && event.key === 'F10'" in terminal
    assert '@contextmenu.prevent="openContextMenu"' in terminal
    assert 'class="terminal-context-menu"' in terminal
    assert 'role="menu"' in terminal
    assert 'role="menuitem"' in terminal

    for label in (
        "复制选中文本",
        "复制全部",
        "粘贴",
        "清屏",
        "搜索终端",
        "查看会话日志",
        "断开连接",
        "重新连接",
    ):
        assert label in terminal

    assert "terminal?.getSelection()" in terminal
    assert "terminalBufferText" in terminal
    assert "terminal?.clear()" in terminal
    assert "navigator.clipboard.readText()" in terminal
    assert "navigator.clipboard.writeText" in terminal
    assert "socket?.send(JSON.stringify({ type: 'terminal.input', data: text }))" in terminal
    assert ".terminal-context-menu" in styles
    assert ".terminal-context-menu button:disabled" in styles
    assert ".terminal-context-menu button:focus-visible" in styles


def test_electron_session_tabs_keep_close_actions_without_crowding_tab_rail() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "function closeSessionsRelative" in store
    for mode in ("'current'", "'left'", "'right'", "'others'", "'all'"):
        assert mode in store
    assert "function closeActiveSession" in store
    assert "function closeOtherSessions" in store
    assert "function closeAllSessions" in store
    assert "Promise.all(closingIds.map" in store

    assert "const sessionContextMenu = ref" in app
    assert "function openSessionContextMenu" in app
    assert "function handleSessionTabKeydown" in app
    assert "event.key === 'ContextMenu'" in app
    assert "event.shiftKey && event.key === 'F10'" in app
    assert '@contextmenu.prevent="openSessionContextMenu($event, session)"' in app
    assert ':data-session-tab-id="session.id"' in app
    assert "workspace.closeSessionsRelative(session.id, mode, session.device_id)" in app
    assert "const scoped = deviceId" in store
    assert "snapshot.filter((session) => session.device_id === deviceId)" in store
    assert "const closingDeviceId = sessions.value.find" in store
    assert "session.device_id === closingDeviceId" in store

    for label in (
        "关闭当前页签",
        "关闭左侧页签",
        "关闭右侧页签",
        "关闭其他页签",
        "关闭所有页签",
        "定位到设备列表",
        "打开设备管理口",
        "打开 Linux 后台",
        "打开串口",
    ):
        assert label in app
    assert 'class="session-tab-actions"' not in app
    assert ".session-tab-actions" not in styles
    assert ".session-context-menu" in styles
    assert ".session-context-menu button:disabled" in styles
    assert ".session-context-menu button:focus-visible" in styles


def test_electron_terminal_header_tracks_active_session_and_keeps_actions_compact() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    terminal = TERMINAL_PANE.read_text(encoding="utf-8")
    split = TERMINAL_SPLIT_WORKSPACE.read_text(encoding="utf-8")
    manager = SESSION_MANAGER.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "const liveWorkspaceTitle = computed" in app
    assert "const session = workspace.activeSession" in app
    assert "workspace.devices.find((device) => device.id === session.device_id)?.name" in app
    assert 'data-testid="live-workspace-title"' in app
    assert 'v-if="!workspace.sessions.length || sessionTabLayout !== \'top\'"' in app
    assert ":data-testid=\"group.id === activeSessionDeviceId ? 'live-workspace-title' : undefined\"" in app
    assert "const sessionDeviceGroups = computed" in app
    assert "const activeDeviceSessions = computed" in app
    assert "const activeProtocolLabels = computed" in app
    assert "const lastActiveSessionByDevice = ref" in app
    assert "function activateSessionDevice" in app
    assert "function sessionKindLabel" in app
    assert 'class="device-session-tabs"' in app
    assert 'class="session-tabs session-child-tabs"' in app
    assert 'v-for="session in activeDeviceSessions"' in app
    assert ':sessions="activeDeviceSessions"' in app
    assert ':key="activeSessionDeviceId"' in app
    assert "const sessionDisplayLabels = computed" in manager
    assert "function sessionAccessibleLabel" in manager
    assert manager.count("sessionAccessibleLabel(session)") >= 4

    bottom_toolbar = terminal.split(
        '<footer class="terminal-bottom-toolbar"', 1
    )[1].split("</footer>", 1)[0]
    for title in (
        "查看会话日志",
        "打开当前会话自动响应",
        "托管传输当前设备",
        "升级当前设备系统包",
        "搜索终端 (Ctrl+F)",
        "缩小字体 (Ctrl+-)",
        "放大字体 (Ctrl++)",
    ):
        assert title in bottom_toolbar
    for title in ("当前会话与设备操作", "断开连接", "重新连接 (Ctrl+Shift+R)"):
        assert title in bottom_toolbar

    assert 'class="split-session-tab"' not in split
    assert 'class="split-pane-session-title"' in split
    assert ':data-session-id="activeSessionFor(pane)!.id"' in split
    assert ".split-pane-session-title" in styles
    assert "grid-template-rows: minmax(0, 1fr) 34px" in styles
    assert ':data-session-kind="session.kind"' in terminal
    assert ':aria-label="`${session.title} 会话控制`"' in terminal
    assert 'class="terminal-toolbar"' not in terminal
    assert ".terminal-bottom-toolbar" in styles
    assert "bottom: 34px" in styles
    assert '<template v-if="!splitDirection && focusedPane === pane" #bottom-leading>' in split
    assert '<TerminalQuickToolbar v-if="splitDirection" />' in split
    assert "<TerminalQuickToolbar />" in split
    assert '<slot name="bottom-leading"></slot>' in terminal
    assert "grid-template-rows: minmax(0, 1fr)" in styles
    assert ".terminal-workspace-stack.split" in styles
    assert ".terminal-bottom-leading" in styles
    assert ".device-session-tabs" in styles
    assert ".session-child-tabs" in styles


def test_electron_profile_list_keeps_legacy_context_menu_actions() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "const profileContextMenu = ref" in app
    assert "function openProfileContextMenu" in app
    assert "function handleProfileKeydown" in app
    assert "event.key === 'ContextMenu'" in app
    assert "event.shiftKey && event.key === 'F10'" in app
    assert '@contextmenu.prevent="openProfileContextMenu($event, profile)"' in app
    assert ':data-profile-row-id="profile.id"' in app
    assert 'class="profile-context-menu"' in app
    assert "profileConnectionCopyText" in app
    assert "navigator.clipboard.writeText(text)" in app
    assert "workspace.openProfileSession(profile, kind)" in app
    assert "workspace.manageProfileCredential(profile, kind)" in app
    assert "showProfileDialog(profile.profile_type, profile)" in app
    assert "workspace.deleteProfile(profile.id)" in app
    assert "moveProfileToGroupFromContext" in app
    assert "workspace.saveProfile(" in app

    for label in (
        "打开",
        "打开 SSH",
        "打开设备管理口",
        "打开串口",
        "复制连接信息",
        "管理 SSH 凭据",
        "管理 Telnet 凭据",
        "管理串口凭据",
        "移动到未分组",
        "编辑",
        "删除",
    ):
        assert label in app

    assert ".profile-context-menu" in styles
    assert ".profile-context-menu button:disabled" in styles
    assert ".profile-context-menu button:focus-visible" in styles
    assert ".danger-menu-item" in styles


def test_electron_server_groups_remember_collapsed_state() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    smoke = MAIN_TS.read_text(encoding="utf-8")

    assert "device-tui.desktop-v2.profile-collapsed-groups" in app
    assert "storedCollapsedProfileGroups" in app
    assert "profileGroupCollapsed" in app
    assert "toggleProfileGroup" in app
    assert "expandProfileGroup(saved.group)" in app
    assert "if (group) expandProfileGroup(group)" in app
    assert ':data-profile-group-name="group.name"' in app
    assert ':data-collapsed="profileGroupCollapsed(group.name)"' in app
    assert ':aria-expanded="!profileGroupCollapsed(group.name)"' in app
    assert 'v-show="!profileGroupCollapsed(group.name)"' in app
    assert "workspace.profileQuery.trim()" in app
    assert "workspace.profileQuery = ''" in app
    assert 'class="navigator-empty-state" role="status"' in app
    assert "visibleProfileCredentialCount" in app
    assert "visibleProfileGroupCount" in app
    assert 'class="profile-summary-row"' in app
    assert "profile-summary-row .attention" in styles
    assert ".profile-group-toggle" in styles
    assert ".profile-summary-row" in styles
    assert ".profile-group-toggle:focus-visible" in styles
    assert "serverGroupCollapsePersistsAndSearchTemporarilyExpands" in smoke
    assert "serverGroupMoveExpandsDestinationWithoutLosingProfile" in smoke
    assert "serverGroupCollapsedStateRestored" in smoke


def test_electron_command_workspace_keeps_find_replace_feedback() -> None:
    command = COMMAND_WORKSPACE.read_text(encoding="utf-8")

    assert "const findStatus = ref('')" in command
    assert "const currentMatchIndex = computed" in command
    assert "const matchLabel = computed" in command
    assert "未找到:" in command
    assert "已替换 ${count} 处命令文本。" in command
    assert "已替换当前匹配。" in command
    assert "@select=\"updateSelectionState\"" in command
    assert "findStatus || matchLabel" in command


def test_electron_shortcuts_are_scoped_and_discoverable() -> None:
    command = COMMAND_WORKSPACE.read_text(encoding="utf-8")
    terminal = TERMINAL_PANE.read_text(encoding="utf-8")

    assert "function handleWorkspaceShortcut" in command
    assert '@keydown.capture="handleWorkspaceShortcut"' in command
    assert "event.key.toLocaleLowerCase() !== 'f'" in command
    assert "function openFindReplace" in command
    assert "function closeFindReplace" in command
    assert "查找和替换 (Ctrl+F)" in command
    assert '@keydown.esc.prevent.stop="closeFindReplace"' in command

    assert "const pane = ref<HTMLElement | null>(null)" in terminal
    assert 'ref="pane"' in terminal
    assert "pane.value.contains(document.activeElement)" in terminal
    assert "搜索终端 (Ctrl+F)" in terminal
    assert "重新连接 (Ctrl+Shift+R)" in terminal


def test_electron_command_workspace_keeps_legacy_context_menu_shortcuts() -> None:
    command = COMMAND_WORKSPACE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "const commandGroupContextMenu = ref" in command
    assert "const editorContextMenu = ref" in command
    assert "function openCommandGroupContextMenu" in command
    assert "function handleCommandGroupKeydown" in command
    assert "function openEditorContextMenu" in command
    assert "event.key === 'ContextMenu'" in command
    assert "event.shiftKey && event.key === 'F10'" in command
    assert '@contextmenu.prevent="openCommandGroupContextMenu($event, group.id, group.name)"' in command
    assert '@contextmenu.prevent="openEditorContextMenu"' in command
    assert 'class="command-context-menu"' in command
    assert 'role="menuitem"' in command

    for label in (
        "重命名",
        "新增命令页签",
        "删除页签",
        "复制选中/当前命令",
        "粘贴",
        "选择当前行",
        "发送到终端",
        "广播发送",
        "查找和替换",
        "清空当前页签",
    ):
        assert label in command

    assert "navigator.clipboard.writeText(command)" in command
    assert "navigator.clipboard.readText()" in command
    assert '@click="closeCommandGroupContextMenu(); closeEditorContextMenu()"' in command
    assert "selectCurrentCommandLine" in command
    assert "clearCurrentCommandGroup" in command
    assert ".command-context-menu" in styles
    assert ".command-context-menu button:disabled" in styles
    assert ".danger-menu-item" in styles
    assert "dispatchScopeLabel" in command
    assert "dispatchTargetLabel" in command
    assert ".command-dispatch-context" in styles


def test_electron_command_panel_height_is_resizable_and_persistent() -> None:
    command = COMMAND_WORKSPACE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")

    assert "device-tui.desktop-v2.command-panel-height" in command
    assert "COMMAND_PANEL_MIN_HEIGHT = 180" in command
    assert "availableCommandPanelHeight" in command
    assert "startCommandPanelResize" in command
    assert "resizeCommandPanel" in command
    assert "handleCommandPanelResizeKeydown" in command
    assert "window.addEventListener('resize', clampCommandPanelHeight)" in command
    assert 'data-testid="command-resize-handle"' in command
    assert 'role="separator"' in command
    assert 'aria-orientation="horizontal"' in command
    assert ':aria-valuenow="commandPanelHeight"' in command
    assert '@dblclick="resetCommandPanelHeight"' in command
    assert ".command-resize-handle" in styles
    assert ".command-resize-handle:focus-visible" in styles
    assert "commandPanelDragResizePersistsAndClampsToWindow" in main
    assert "commandPanelHeightRestored" in main


def test_electron_empty_workspace_does_not_leave_a_dead_command_region() -> None:
    styles = STYLES_CSS.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")

    assert ".workspace-stage { display: flex; flex-direction: column;" in styles
    assert "flex: 1;" in styles
    assert "emptyWorkspaceCommandBarHasNoDeadClickRegion" in main


def test_electron_device_detail_shares_left_navigator() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")

    navigator_detail = app.index('class="navigator-detail"')
    workspace = app.index('<main class="workspace-stage">')
    assert navigator_detail < workspace
    assert "device-tui.desktop-v2.navigator-detail-collapsed" in app
    assert 'aria-label="设备与连接详情"' in app
    assert ".navigator-detail-content" in styles
    assert "deviceDetailSharesLeftNavigator" in main
    assert "navigatorDetailCollapsePersists" in main


def test_electron_device_navigator_width_is_resizable_and_persistent() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")

    assert "device-tui.desktop-v2.navigator-width" in app
    assert 'data-testid="navigator-resize-handle"' in app
    assert 'role="separator"' in app
    assert 'aria-orientation="vertical"' in app
    assert ':aria-valuenow="effectiveNavigatorWidth"' in app
    assert '@pointerdown="startNavigatorResize"' in app
    assert '@keydown="handleNavigatorResizeKeydown"' in app
    assert '@dblclick="resetNavigatorWidth"' in app
    assert "var(--navigator-width" in styles
    assert ".navigator-resize-handle" in styles
    assert ".navigator-resize-handle:focus-visible" in styles
    assert "navigatorWidthResizePersists" in main
    assert "navigatorWidthRestored" in main


def test_electron_session_manager_uses_a_non_overlay_grid_column() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")

    responsive_styles = styles[styles.index("@media (max-width: 1680px)"):styles.index("@media (max-width: 900px)")]
    assert ".app-shell.has-session-sidebar" in responsive_styles
    assert "minmax(460px, 1fr) auto" in responsive_styles
    assert "minmax(440px, 1fr) auto" in responsive_styles
    assert "minmax(420px, 1fr) auto" in responsive_styles
    assert "position: fixed" not in responsive_styles
    assert "session-sidebar-collapsed" in responsive_styles
    assert "const showSessionSidebar = computed" in app
    assert "const sideManagerReserve = showSessionSidebar.value" in app
    assert "sessionManagerDoesNotOverlayTerminal" in main


def test_electron_device_controls_use_compact_progressive_disclosure() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert 'class="device-connection-panel"' in app
    assert "管理地址" in app
    assert "IP、端口、账号、密码均可修改" in app
    assert "openCustomDeviceSession(workspace.selectedDevice, 'ssh')" in app
    assert "openCustomDeviceSession(workspace.selectedDevice, 'telnet')" in app
    assert "openCustomDeviceSession(workspace.selectedDevice, 'serial')" in app
    assert 'class="connection-actions connection-menu"' not in app
    assert 'class="primary-button device-lease-button"' in app
    assert 'class="device-more-details"' in app
    assert "更多设备信息" in app
    assert ".device-connection-panel" in styles
    assert "一键连接 SSH" in app
    assert "一键连接 Telnet" in app
    assert "一键连接串口" in app
    assert 'aria-label="编辑 SSH 连接"' in app
    assert ".device-protocol-action" in styles
    assert ".device-protocol-connect" in styles
    assert ".device-protocol-edit" in styles
    assert ".device-lease-button" in styles
    assert ".device-more-details" in styles
    assert "min-height: 50px" in styles


def test_electron_command_dispatch_keeps_legacy_empty_target_feedback() -> None:
    store = WORKSPACE_STORE.read_text(encoding="utf-8")

    assert "请先选中要发送的命令" in store
    assert "当前没有打开的终端会话" in store
    assert "当前没有已连接的终端会话" in store
    assert "connectedSessions.value.length" in store


def test_electron_terminal_log_panel_can_copy_log_content() -> None:
    terminal = TERMINAL_PANE.read_text(encoding="utf-8")

    assert "Clipboard" in terminal
    assert "const logNotice = ref('')" in terminal
    assert "async function copyLog" in terminal
    assert "navigator.clipboard.writeText(logContent.value)" in terminal
    assert "暂无日志可复制" in terminal
    assert "已复制全部日志" in terminal
    assert "已复制日志尾部内容" in terminal
    assert 'title="复制日志"' in terminal
    assert ':disabled="!logContent"' in terminal
    assert "读取日志失败:" in terminal
    assert "async function openLogDirectory" in terminal
    assert "async function saveLogCopy" in terminal
    assert "openSessionLogDirectory()" in terminal
    assert "saveSessionLog({" in terminal
    assert "打开日志目录" in terminal
    assert "保存日志副本" in terminal
    assert "日志副本已保存" in terminal


def test_electron_settings_and_log_actions_restore_legacy_controls() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    settings = SETTINGS_PANEL.read_text(encoding="utf-8")
    help_panel = HELP_PANEL.read_text(encoding="utf-8")
    terminal = TERMINAL_PANE.read_text(encoding="utf-8")

    assert "showSettingsPanel" in app
    assert "showHelpPanel" in app
    assert "<SettingsPanel" in app
    assert "<HelpPanel" in app
    for label in ("工作台设置", "会话页签布局", "右侧会话栏默认折叠", "终端字体大小", "会话日志", "保存目录", "单个日志分卷大小"):
        assert label in settings
    assert "chooseSessionLogDirectory()" in settings
    assert "updateSessionLogSettings" in settings
    assert "device-tui:terminal-font-size" in settings
    assert "settings-behavior-note" in settings
    assert "logSettingsDirty" in settings
    assert "settings-dirty-state" in settings
    assert "settings-log-skeleton" in settings
    assert "settings-action-bar" in settings
    assert 'aria-label="正在读取日志设置"' in settings
    assert "操作帮助" in help_panel
    assert "安全边界" in help_panel
    assert "shortcutGroups" in help_panel
    assert "help-shortcut-group" in help_panel
    assert "visibleGroups" in help_panel
    assert 'aria-label="搜索操作帮助"' in help_panel
    assert 'class="help-categories"' in help_panel
    assert "没有匹配的操作" in help_panel
    assert "启动 FTP/SFTP 服务" in help_panel
    assert "拖动会话页签" in help_panel
    assert "双击分隔线" in help_panel
    assert "async function createNewLog" in terminal
    assert "async function openCurrentLog" in terminal
    assert "createSessionLog(props.session.id)" in terminal
    assert "openCurrentSessionLog(props.session.id)" in terminal
    assert "新建日志" in terminal
    assert "打开当前会话日志" in terminal
    assert "打开当前会话自动响应" in terminal
    assert "openSessionAutomation" in app
    assert ".session-sidebar .session-manager" in STYLES_CSS.read_text(encoding="utf-8")
    assert "session-rail-toggle" in SESSION_MANAGER.read_text(encoding="utf-8")
    assert "展开右侧会话栏" in SESSION_MANAGER.read_text(encoding="utf-8")
    assert "折叠右侧会话栏" in SESSION_MANAGER.read_text(encoding="utf-8")


def test_connection_profile_dialog_explains_and_enforces_readiness() -> None:
    dialog = PROFILE_DIALOG.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "const formReady = computed" in dialog
    assert "const formReadinessText = computed" in dialog
    assert 'class="profile-readiness"' in dialog
    assert ':disabled="saving || !formReady"' in dialog
    assert '@keydown.esc.prevent="emit(\'close\')"' in dialog
    assert "protocol-host-field" in dialog
    assert "protocol-user-field" in dialog
    assert ".profile-readiness" in styles
    assert ".protocol-field" in styles


def test_electron_modal_dialogs_share_keyboard_focus_management() -> None:
    focus = DIALOG_FOCUS.read_text(encoding="utf-8")
    settings = SETTINGS_PANEL.read_text(encoding="utf-8")
    help_panel = HELP_PANEL.read_text(encoding="utf-8")
    profile = PROFILE_DIALOG.read_text(encoding="utf-8")
    group = GROUP_DIALOG.read_text(encoding="utf-8")
    quick_toolbar = TERMINAL_QUICK_TOOLBAR.read_text(encoding="utf-8")

    assert "export function useDialogFocus" in focus
    assert "event.key !== 'Tab'" in focus
    assert "restoreTarget" in focus
    assert "target?.isConnected" in focus
    for component in (settings, help_panel, profile, group, quick_toolbar):
        assert "useDialogFocus" in component
        assert '@keydown="handleDialogKeydown"' in component
        assert "data-dialog-initial-focus" in component


def test_electron_terminal_connection_failures_stay_inline_and_actionable() -> None:
    terminal = TERMINAL_PANE.read_text(encoding="utf-8")
    status = SESSION_STATUS.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "const connectionStatusLabel = computed" in terminal
    for label in ("正在连接", "已连接", "已断开", "通道已分离", "连接错误", "连接失败"):
        assert label in terminal or label in status
    assert "[终端连接失败]" in terminal
    assert "[终端通道错误] 请重新连接。" in terminal
    assert "emit('status', props.session.id, 'error', lastSequence)" in terminal
    assert "['disconnected', 'error', 'failed', 'closed']" in terminal
    assert '.connection-state[data-state="connecting"]' in styles
    assert '.connection-state[data-state="detached"]' in styles
    assert '.connection-state[data-state="failed"]' in styles
    assert '.connection-state[data-state="disconnected"]' in styles
    assert '.session-tab-select > i[data-state="connecting"]' in styles
    assert '.session-tab-select > i[data-state="disconnected"]' in styles
    assert '.session-tab-select > i[data-state="failed"]' in styles
    assert 'aria-label="`连接状态：${connectionStatusLabel}`"' in terminal
    assert "sessionStatusLabel" in APP_VUE.read_text(encoding="utf-8")
    session_manager = SESSION_MANAGER.read_text(encoding="utf-8")
    assert "function sessionAccessibleLabel" in session_manager
    for label in ("连接错误", "通道已分离", "已关闭"):
        assert label in status
    assert "const recoveryMessage = computed" in terminal
    assert 'class="terminal-recovery-banner"' in terminal
    assert ".terminal-pane.has-recovery" in styles
    assert ".terminal-recovery-banner" in styles
    assert 'class="terminal-recovery-action-label"' in terminal
    assert "@container (max-width: 560px)" in styles


def test_electron_device_session_groups_expose_aggregate_health() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    manager = SESSION_MANAGER.read_text(encoding="utf-8")
    status = SESSION_STATUS.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "export function aggregateSessionHealth" in status
    assert "export function sessionHealthLabel" in status
    assert "export function sessionHealthShortLabel" in status
    assert status.index("statuses.has('failed')") < status.index("statuses.has('disconnected')")
    assert status.index("statuses.has('disconnected')") < status.index("statuses.has('connecting')")
    assert "health: aggregateSessionHealth(sessions)" in app
    assert "sessionHealthLabel(group.health)" in app
    assert "groupAccessibleLabel" in manager
    assert 'class="device-session-health"' in app
    assert 'class="device-session-health"' in manager
    assert 'class="device-session-health-label"' in app
    assert 'class="device-session-health-label"' in manager
    for state in ("connected", "connecting", "disconnected", "failed"):
        assert f'.device-session-health[data-state="{state}"]' in styles
        assert f'.device-session-health-label[data-state="{state}"]' in styles


def test_electron_context_menus_clamp_to_viewport_and_focus_first_action() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    terminal = TERMINAL_PANE.read_text(encoding="utf-8")
    command = COMMAND_WORKSPACE.read_text(encoding="utf-8")
    context_menu = CONTEXT_MENU.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "export function clampContextMenuPoint" in context_menu
    assert "export function clampContextMenuElement" in context_menu
    assert "export function focusFirstContextMenuItem" in context_menu
    assert "export function handleContextMenuKeydown" in context_menu
    assert "export function restoreContextMenuFocus" in context_menu
    assert "export function contextMenuTrigger" in context_menu
    assert "window.innerWidth - width" in context_menu
    assert "window.innerHeight - height" in context_menu
    for key in ("ArrowDown", "ArrowUp", "Home", "End", "Escape"):
        assert key in context_menu
    for source in (app, terminal, command):
        assert "clampContextMenuPoint" in source
        assert "clampContextMenuElement" in source
        assert "focusFirstContextMenuItem" in source
    assert "max-height: calc(100vh - 16px)" in styles
    assert "overflow-y: auto" in styles


def test_electron_device_loading_state_uses_table_aligned_skeleton() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert 'class="navigator-loading"' in app
    assert 'aria-label="正在载入设备"' in app
    assert 'class="device-loading-row"' in app
    assert ".device-loading-row" in styles
    assert "@keyframes device-loading-shimmer" in styles


def test_electron_transfer_files_are_height_bounded_and_show_loading_feedback() -> None:
    transfer = Path(
        "desktop/src/renderer/src/components/TransferWorkspace.vue"
    ).read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "const transferFilesLoading = ref(false)" in store
    assert "transferFilesLoading.value = true" in store
    assert "transferFilesLoading.value = false" in store
    assert ':aria-busy="workspace.transferFilesLoading"' in transfer
    assert 'class="transfer-file-loading"' in transfer
    assert "正在读取共享目录" in transfer
    assert ".transfer-files-card { max-height:" in styles
    assert "scrollbar-gutter: stable" in styles
    assert ".transfer-file-loading" in styles


def test_electron_automation_workspace_keeps_runtime_feedback() -> None:
    automation = AUTOMATION_WORKSPACE.read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    app = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "event.type.startsWith('automation.')" in store
    assert "void refreshAutomation()" in store
    for message in (
        "自动化已启动",
        "自动化已完成",
        "自动化等待下一步输出",
        "自动化执行失败",
        "自动化已取消",
    ):
        assert message in store
    assert "typeof data.message === 'string'" in store

    assert "const activeTriggeredIds = computed" in automation
    assert "const activeWaitingIds = computed" in automation
    assert "const runningRuleNames = computed" in automation
    assert "const waitingRuleNames = computed" in automation
    assert "const triggeredRuleNames = computed" in automation
    assert "const automationStatusText = computed" in automation
    assert "当前会话暂无运行中的自动响应" in automation
    assert "已触发" in automation
    assert "automation-session-status" in automation
    assert "data-state=\"running\"" in styles
    assert "data-state=\"waiting\"" in styles
    assert "data-state=\"triggered\"" in styles

    assert 'class="notice-banner"' in app
    assert 'role="status"' in app
    assert "const noticeRequiresAttention = computed" in app
    assert "function clearWorkspaceNotice" in app
    assert "setTimeout" in app
    assert 'title="关闭通知"' in app
    assert 'class="action-notice"' not in app
    assert 'workspace.error && !backendFailure' in app
    assert 'role="alert"' in app
    assert "async function retryWorkspaceRecovery" in app
    assert 'title="立即重试工作区"' in app
    assert "workspaceRecoveryBusy" in app
    assert 'data-state="backend"' in app
    assert ".notice-banner" in styles
    assert '.notice-banner[data-state="attention"]' in styles
    assert ".system-banner > button" in styles


def test_electron_automation_editor_protects_unsaved_drafts() -> None:
    automation = AUTOMATION_WORKSPACE.read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    app = APP_VUE.read_text(encoding="utf-8")
    smoke = MAIN_TS.read_text(encoding="utf-8")

    assert "const isDirty = computed" in automation
    assert "const creatingNew = ref(false)" in automation
    assert "record.id === loadedRuleId.value && isDirty.value" in automation
    assert "当前规则有未保存修改" in automation
    assert "registerAutomationCloseGuard(prepareClose)" in automation
    assert "window.addEventListener('beforeunload', warnBeforeUnload)" in automation
    assert 'class="automation-draft-state"' in automation

    assert "function registerAutomationCloseGuard" in store
    assert "function closeAutomationPanel(): boolean" in store
    assert "automationCloseGuard && !automationCloseGuard()" in store
    assert "workspace.closeAutomationPanel()" in app

    assert "automationUnsavedDraftGuardsClose" in smoke
    assert "unsavedCloseStayedOpen" in smoke
    assert "confirmedCloseSucceeded" in smoke


def test_electron_automation_rule_list_supports_search_and_status_filters() -> None:
    automation = AUTOMATION_WORKSPACE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    smoke = MAIN_TS.read_text(encoding="utf-8")

    assert "const ruleQuery = ref('')" in automation
    assert "const filteredAutomationRules = computed" in automation
    assert "ruleStatusFilter.value === 'active'" in automation
    assert "v-for=\"record in filteredAutomationRules\"" in automation
    assert 'aria-label="搜索自动化规则"' in automation
    assert 'aria-label="筛选自动化规则状态"' in automation
    assert "event.key.toLocaleLowerCase() === 'f'" in automation
    assert "ruleSearchInput.value?.focus()" in automation
    assert "没有匹配的规则" in automation

    assert ".automation-rule-tools" in styles
    assert ".automation-rule-search:focus-within" in styles
    assert "automationRuleSearchAndFilter" in smoke
    assert "automationEscapeClearedSearch" in smoke


def test_electron_automation_rules_can_be_safely_cloned() -> None:
    automation = AUTOMATION_WORKSPACE.read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    api = Path("desktop/src/renderer/src/transport/api.ts").read_text(encoding="utf-8")
    backend = Path("src/desktop_backend/app.py").read_text(encoding="utf-8")
    smoke = MAIN_TS.read_text(encoding="utf-8")

    assert 'data-testid="automation-clone"' in automation
    assert "async function cloneSelected" in automation
    assert "workspace.cloneAutomationRule(record.id)" in automation
    assert "创建默认停用的独立副本" in automation

    assert "async function cloneAutomationRule" in store
    assert "desktopApi.cloneAutomationRule(ruleId)" in store
    assert "cloneAutomationRule: (ruleId: string)" in api
    assert '"/api/v1/automation/rules/{rule_id}/clone"' in backend

    assert "automationCloneCreatesDisabledIndependentRule" in smoke
    assert "cloneSmokeAssertions" in smoke


def test_electron_automation_workspace_shows_recent_execution_activity() -> None:
    automation = AUTOMATION_WORKSPACE.read_text(encoding="utf-8")
    store = WORKSPACE_STORE.read_text(encoding="utf-8")
    types = TYPES_TS.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    backend = Path("src/desktop_backend/app.py").read_text(encoding="utf-8")
    smoke = MAIN_TS.read_text(encoding="utf-8")

    assert "interface AutomationActivityRecord" in types
    assert "activity: AutomationActivityRecord[]" in types
    assert "const automationActivity = ref<AutomationActivityRecord[]>([])" in store
    assert "automationActivity.value = response.activity || []" in store

    assert "const recentActivity = computed" in automation
    assert 'class="automation-activity-panel"' in automation
    assert 'class="automation-activity-row"' in automation
    assert "function activityLabel" in automation
    assert "function activityTarget" in automation
    assert ".automation-activity-list" in styles
    assert '.automation-activity-row[data-event="failed"]' in styles

    assert "desktop.automation.activities(limit=100)" in backend
    assert "automationActivityShowsLifecycle" in smoke


def test_electron_ui_parity_smoke_gate_covers_visible_regressions() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    package = PACKAGE_JSON.read_text(encoding="utf-8")
    main = MAIN_TS.read_text(encoding="utf-8")
    smoke = UI_PARITY_SMOKE.read_text(encoding="utf-8")

    assert '"smoke:ui-parity": "npm run build && node scripts/smoke-ui-parity.mjs"' in package
    assert "DEVICE_TUI_CAPTURE_UI_PARITY" in main
    assert "DEVICE_TUI_CAPTURE_HELP_PATH" in main
    assert "DEVICE_TUI_CAPTURE_HELP_LIGHT_PATH" in main
    assert "uiParityPassed" in main
    assert "uiRestorePassed" in main
    assert "backendRecoveryPassed" in main
    assert "backend.crashForRecoveryProbe()" in main
    assert "backend:recovered" in main
    assert "stopApplicationEvents = null" in app
    assert "Python 后端已自动恢复，工作区已重新载入。" in app
    for label in (
        "multiSessionCountRestored",
        "activeSessionRestored",
        "selectedDeviceRowRestored",
        "themeRestored",
        "alwaysOnTopRestored",
        "sessionTabLayoutRestored",
        "sessionTabRailCollapsedRestored",
        "rightSessionSidebarRestored",
        "navigatorDetailStateRestored",
        "tokenStillHiddenAfterReload",
    ):
        assert label in main

    for selector in (
        ".device-table-header",
        ".device-table-row",
        ".summary-clear",
        ".navigator-detail",
        ".session-sidebar",
        ".theme-toggle",
        ".device-context-menu",
        ".session-context-menu",
        ".terminal-context-menu",
        ".command-context-menu",
        ".profile-context-menu",
    ):
        assert selector in main

    for label in (
        "序号",
        "板类型",
        "legacyDeviceColumnsFitWithoutHorizontalScroll",
        "deviceKeywordSearchFiltersAndKeepsSelection",
        "deviceDomainFilterUpdatesRowsAndClearAction",
        "deviceStatusFilterUpdatesRowsAndClearAction",
        "deviceCpuFilterUpdatesRowsAndClearAction",
        "deviceSearchNoResultsIsActionable",
        "emptyWorkspaceActionFollowsSelectedDevice",
        "deviceSessionTabsSummarizeWorstSessionHealth",
        "contextMenusStayInsideViewportAndFocusFirstAction",
        "contextMenusSupportKeyboardNavigationAndRestoreFocus",
        "globalNoticeIsSemanticAndDismissible",
        "deviceClearFiltersRestoresAllRows",
        "ownedDeviceCountUsesUniqueIdsWhileFilterKeepsBoardRows",
        "legacyStatusBucketsClassifyPipelineBeforeOccupied",
        "legacyInventoryHasTwentyOneRows",
        "simulatedTerminalAppearsExactlyOnce",
        "simulatedTerminalOnlyOffersSimulatedSession",
        "simulatedTerminalDeviceActionsAreDisabledWithReason",
        "disabledConnectionActionsExplainReason",
        "connectionProfileReadinessPreventsIncompleteSave",
        "复制设备行",
        "关闭当前页签",
        "复制选中文本",
        "查找和替换",
        "commandFindShortcutOpensWithoutTerminalConflict",
        "commandFindEscapeCloses",
        "commandDispatchWritesTerminalOutput",
        "commandHistoryRecordsUiDispatch",
        "terminalLogPanelShowsSessionLog",
        "terminalLogCopyControlAvailable",
        "terminalLogExportCreatesSafeCopy",
        "terminalLogDirectoryActionWorks",
        "settingsPanelExposesLegacyControls",
        "settingsDialogTrapsAndRestoresFocus",
        "settingsTerminalFontAppliesImmediately",
        "sessionTabSideLayoutAppliesAndPersists",
        "sessionTabCollapsedPreferenceAppliesAndPersists",
        "collapsedSessionRailRemainsAccessibleAndRestorable",
        "terminalAutomationQuickAccessTargetsCurrentSession",
        "settingsLogDirectoryAndRotationPersist",
        "settingsUnsavedLogChangesAreVisible",
        "settingsActionsRemainVisibleOutsideScrollRegion",
        "quickSendDialogManagesKeyboardFocus",
        "helpPanelIsFunctional",
        "modalPanelsKeepKeyboardFocusContained",
        "terminalCurrentLogNativeOpenWorks",
        "terminalManualNewLogWorks",
        "terminalDisconnectShowsInlineFeedback",
        "terminalReconnectRestoresConnectedState",
        "sshFailureShowsInlineReasonAndRetry",
        "sshFailureRetryStaysInline",
        "telnetFailureShowsInlineReasonAndRetry",
        "serialClaimAndFailureFlowStaysInline",
        "connectionDialogsManageKeyboardFocus",
        "connectionDialogRestoresTriggerFocus",
    ):
        assert label in main

    assert "DEVICE_TUI_CAPTURE_TERMINAL: '1'" in smoke
    assert "DEVICE_TUI_CAPTURE_UI_PARITY: '1'" in smoke
    assert "DEVICE_TUI_CAPTURE_LIGHT_PATH" in smoke
    assert "DEVICE_TUI_CAPTURE_SETTINGS_PATH" in smoke
    assert "DEVICE_TUI_CAPTURE_SETTINGS_LIGHT_PATH" in smoke
    assert "DEVICE_TUI_CAPTURE_HELP_PATH" in smoke
    assert "DEVICE_TUI_CAPTURE_HELP_LIGHT_PATH" in smoke
    assert "DEVICE_TUI_CAPTURE_BACKEND_RECOVERY: '1'" in smoke
    assert "DEVICE_TUI_DISABLE_EXTERNAL_OPEN: '1'" in smoke
    assert "DEVICE_TUI_LOG_EXPORT_PATH" in smoke
    assert "DEVICE_TUI_LOG_DIRECTORY_SELECTION" in smoke
    assert "DEVICE_TUI_MOCK_PROTOCOL_FAILURE: '1'" in smoke
    assert "DEVICE_TUI_UI_PARITY_TIMEOUT_MS || 90_000" in smoke
    assert "[renderer] uiParityPassed=true" in smoke
    assert "[renderer] uiRestorePassed=true" in smoke
    assert "[renderer] backendRecoveryPassed=true" in smoke
    assert "recoveryActionSeen" in main
    assert "[renderer] tokenExposed=false" in smoke
    assert "ui-parity-light.png" in smoke
    assert "ui-parity-help.png" in smoke
    assert "ui-parity-settings-light.png" in smoke
    assert "ui-parity-help-light.png" in smoke
    assert "session-log-export.log" in smoke
