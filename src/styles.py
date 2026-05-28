from __future__ import annotations

from ._sample_data import STATUS_IDLE, STATUS_OCCUPIED, STATUS_OTHER, STATUS_PIPELINE


STATUS_COLORS = {
    STATUS_IDLE: "#3cc98e",
    STATUS_OCCUPIED: "#f5a623",
    STATUS_PIPELINE: "#5b6ef5",
    STATUS_OTHER: "#808080",
}

APP_STYLE = """
QWidget {
    background: #0b0f14;
    color: #e5edf6;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
    font-size: 13px;
}
QMainWindow {
    background: #0b0f14;
}
QFrame#toolbarFrame,
QFrame#workspaceHeader,
QFrame#sessionToolbar,
QFrame#sessionInfoCard,
QFrame#sessionInputBar,
QFrame#navFilterBar,
QFrame#navStatsBar,
QFrame#myOccupancyCard,
QFrame#activeFilterBar,
QFrame#commandRecordDock,
QGroupBox {
    background: #111820;
    border: 1px solid #202a36;
    border-radius: 10px;
}
QGroupBox {
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
    color: #e7f1ff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    background: transparent;
}
QWidget#centerStage,
QWidget#inspectorRail,
QWidget#leftRail {
    background: transparent;
}
QFrame#sessionEmptyState {
    background: #0f141a;
    border: 1px dashed #334155;
    border-radius: 14px;
}
QScrollArea#inspectorScroll {
    background: transparent;
    border: none;
}
QScrollArea#inspectorScroll > QWidget > QWidget {
    background: transparent;
}
QLabel#sessionEmptyTitle {
    background: transparent;
    color: #f8fbff;
    font-size: 24px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#sessionEmptyCopy {
    background: transparent;
    color: #8ea7c2;
    font-size: 13px;
    line-height: 1.7;
}
QGroupBox#navShell,
QGroupBox#deviceDetailCard,
QGroupBox#quickActionCard,
QGroupBox#authCard {
    border-radius: 12px;
}
QGroupBox#deviceDetailCard {
    border-color: #1b2a38;
    background: #0b1219;
}
QGroupBox#quickActionCard {
    border-color: #315042;
    background: #101820;
}
QGroupBox#authCard {
    background: #0b1219;
    border-color: #1b2a38;
}
QFrame#connectionParamsHeader {
    background: transparent;
    border: none;
    min-height: 28px;
    max-height: 28px;
}
QFrame#connectionParamsPanel {
    background: transparent;
    border: none;
}
QFrame#connectionCompactRow {
    background: #0a0f15;
    border: 1px solid #1d2a38;
    border-radius: 8px;
}
QLabel#connectionKindLabel {
    background: transparent;
    color: #e7f1ff;
    font-size: 12px;
    font-weight: 700;
}
QLabel#connectionMiniLabel {
    background: transparent;
    color: #8ea7c2;
    font-size: 11px;
    font-weight: 600;
}
QGroupBox#navShell {
    border-color: #2a3644;
}
QFrame#navFilterBar {
    background: #0c1218;
    border-color: #273242;
}
QFrame#navStatsBar {
    background: #0c1218;
    border-color: #233548;
}
QFrame#sessionQuickBar {
    background: #090d12;
    border: 1px solid #1a2028;
    border-radius: 8px;
}
QFrame#myOccupancyCard {
    background: #101820;
    border-color: #253444;
}
QFrame#activeFilterBar,
QFrame#commandRecordDock {
    background: #0c1218;
    border-color: #273242;
}
QGroupBox#authCard QGroupBox {
    background: #090f15;
    border: 1px solid #1d2a38;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 14px;
}
QGroupBox#authCard QGroupBox::title {
    color: #8ea7c2;
    font-size: 12px;
    font-weight: 600;
}
QPushButton {
    background: #17212c;
    border: 1px solid #2d3a49;
    border-radius: 8px;
    padding: 8px 14px;
    color: #e5edf6;
}
QPushButton:hover {
    background: #1d2b38;
    border-color: #3f5267;
}
QPushButton:pressed {
    background: #101820;
}
QPushButton:disabled {
    color: #64748b;
    background: #0b1118;
    border-color: #15212e;
}
QPushButton#primaryButton {
    background: #222a33;
    border-color: #4a525e;
    color: #f8fafc;
}
QPushButton#dangerButton {
    background: #4a1f23;
    border-color: #8f2f3a;
    color: #fecaca;
}
QPushButton#ghostButton {
    background: transparent;
    border-color: #303d4d;
}
QPushButton#compactGhostButton {
    background: transparent;
    border-color: #303d4d;
    padding: 7px 10px;
    min-width: 44px;
}
QPushButton#filterToggleButton {
    background: #0b1117;
    border: 1px solid #263544;
    border-radius: 8px;
    color: #a8b5c4;
    padding: 8px 10px;
    font-size: 12px;
    font-weight: 700;
}
QPushButton#filterToggleButton:hover {
    background: #181f27;
    border-color: #464e59;
    color: #f8fafc;
}
QPushButton#filterToggleButton:checked {
    background: #1b222b;
    border-color: #5a626e;
    color: #e5edf6;
}
QPushButton#filterToggleButton:disabled {
    background: #0b1118;
    border-color: #15212e;
    color: #506174;
}
QLineEdit,
QComboBox,
QPlainTextEdit {
    background: #0b1117;
    border: 1px solid #263544;
    border-radius: 8px;
    padding: 8px 10px;
    color: #e5edf6;
    selection-background-color: #2f4050;
}
QLineEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus {
    border-color: #3f5267;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox#sessionJumpCombo {
    background: #0c1218;
    border: 1px solid #243241;
    border-radius: 7px;
    color: #cbd5e1;
    padding: 5px 28px 5px 10px;
    min-height: 24px;
    font-size: 12px;
}
QComboBox#sessionJumpCombo:focus {
    border-color: #525b66;
}
QComboBox#sessionJumpCombo:disabled {
    color: #64748b;
    background: #090e13;
    border-color: #17212c;
}
QScrollBar:vertical {
    background: #0b141d;
    width: 9px;
    margin: 8px 2px 8px 2px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #262f39;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #363f4a;
}
QScrollBar::handle:vertical:pressed {
    background: #4a535e;
}
QScrollBar::sub-line:vertical,
QScrollBar::add-line:vertical {
    height: 0px;
    background: transparent;
    border: none;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: #0b141d;
    height: 12px;
    margin: 2px 6px 2px 6px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal {
    background: #262f39;
    min-width: 28px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background: #363f4a;
}
QScrollBar::handle:horizontal:pressed {
    background: #4a535e;
}
QScrollBar::sub-line:horizontal,
QScrollBar::add-line:horizontal {
    width: 0px;
    background: transparent;
    border: none;
}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
QTableWidget {
    background: #090d12;
    alternate-background-color: #090d12;
    border: 1px solid #1b232d;
    border-radius: 12px;
    gridline-color: transparent;
    selection-background-color: #2c333d;
    selection-color: #f7f9fb;
}
QTableWidget::item {
    padding: 8px 8px;
    border-bottom: 1px solid #141a21;
}
QTableWidget::item:selected {
    background: #2c333d;
    color: #f7f9fb;
}
QTableWidget::item:hover {
    background: #111821;
}
QTableWidget::item:focus {
    border: none;
    outline: none;
}
QTableWidget#deviceTable {
    border-color: #1d2630;
}
QHeaderView::section {
    background: #090d12;
    color: #7f8c9b;
    padding: 7px 8px;
    border: none;
    border-bottom: 1px solid #1a222c;
    font-weight: 600;
    font-size: 12px;
}
QSplitter::handle {
    background: #0b0f14;
}
QSplitter::handle:horizontal {
    width: 10px;
    margin: 8px 0;
}
QSplitter::handle:horizontal:hover {
    background: #1a2531;
}
QTabWidget::pane {
    border: 1px solid #202731;
    border-radius: 10px;
    background: #0a0f15;
    top: -1px;
}
QTabWidget::tab-bar {
    left: 8px;
}
QTabBar::tab {
    background: #0a0f15;
    color: #8f9dad;
    border: 1px solid #1c242e;
    border-bottom-color: #202731;
    border-radius: 8px;
    padding: 3px 6px;
    min-width: 144px;
    min-height: 23px;
    margin-right: 3px;
    margin-top: 3px;
}
QTabBar::tab:selected {
    background: #121820;
    color: #f7f9fb;
    border-color: #3a424d;
    border-bottom-color: #121820;
    margin-top: 0px;
    min-height: 25px;
}
QTabBar::tab:hover {
    color: #e5edf6;
    background: #10161d;
    border-color: #303945;
}
QWidget#deviceSessionPage {
    background: transparent;
}
QTabWidget#deviceSessionTabs::pane {
    border: none;
    border-radius: 0px;
    background: transparent;
    top: 0px;
}
QTabWidget#deviceSessionTabs::tab-bar {
    left: 4px;
}
QTabWidget#deviceSessionTabs QTabBar::tab {
    background: #090e13;
    border: 1px solid #1b242e;
    border-bottom-color: #222a34;
    border-radius: 7px;
    color: #94a0ae;
    min-width: 72px;
    min-height: 18px;
    padding: 1px 4px;
    margin-right: 3px;
    margin-top: 2px;
}
QTabWidget#deviceSessionTabs QTabBar::tab:selected {
    background: #131920;
    border-color: #373f4a;
    border-bottom-color: #131920;
    color: #f8fafc;
    min-height: 20px;
    margin-top: 0px;
}
QTabWidget#deviceSessionTabs QLabel#tabHeaderLabel {
    font-size: 11px;
}
QWidget#tabHeader {
    background: transparent;
}
QWidget#tabHeader[selected="true"] {
    background: transparent;
}
QLabel#tabStatusDot {
    background: #49627d;
    border-radius: 4px;
}
QLabel#tabStatusDot[connectionState="connecting"] {
    background: #f59e0b;
}
QLabel#tabStatusDot[connectionState="connected"] {
    background: #22c55e;
}
QLabel#tabStatusDot[connectionState="error"] {
    background: #ef4444;
}
QLabel#tabHeaderLabel {
    background: transparent;
    color: #b8c7d9;
    font-size: 12px;
    font-weight: 700;
}
QLabel#tabHeaderLabel[selected="true"] {
    color: #f8fbff;
    font-weight: 700;
}
QToolButton#tabCloseButton {
    background: transparent;
    color: #6f8194;
    border: 1px solid transparent;
    border-radius: 8px;
    font-family: "Arial", "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 12px;
    font-weight: 700;
    padding: 0px;
    margin: 0px;
}
QToolButton#tabCloseButton[selected="true"] {
    background: transparent;
    border-color: transparent;
    color: #8fa1b4;
}
QToolButton#tabCloseButton:hover {
    background: #7f1d1d;
    color: #ffffff;
    border-color: #ef4444;
}
QToolButton#tabCloseButton:pressed {
    background: #5f1717;
    color: #ffffff;
    border-color: #ef4444;
}
QPlainTextEdit#terminalLog {
    background: #06090d;
    color: #d6deeb;
    border: 1px solid #18212b;
    border-radius: 10px;
    font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 15px;
    font-weight: 400;
    padding: 16px 18px;
    selection-background-color: #334155;
    selection-color: #f8fafc;
}
QPlainTextEdit#terminalLog:focus {
    border-color: #3b4450;
}
QWidget#terminalLog {
    background: #06090d;
    color: #d6deeb;
    border: 1px solid #18212b;
    border-radius: 10px;
    font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 15px;
    font-weight: 400;
}
QWidget#terminalLog:focus {
    border-color: #3b4450;
}
QScrollBar#terminalScrollBar:vertical {
    background: #06090d;
    border: 0;
    width: 14px;
    margin: 2px;
}
QScrollBar#terminalScrollBar::handle:vertical {
    background: #334155;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar#terminalScrollBar::handle:vertical:hover {
    background: #475569;
}
QScrollBar#terminalScrollBar::add-line:vertical,
QScrollBar#terminalScrollBar::sub-line:vertical {
    height: 0;
}
QFrame#commandRecordDock {
    background: #06090d;
    border: 1px solid #151b22;
    border-top-color: #252c35;
    border-radius: 10px;
}
QFrame#commandRecordResizeHandle {
    background: transparent;
    border: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
QFrame#commandRecordResizeHandle:hover {
    background: #202832;
}
QFrame#commandRecordHintBar {
    background: transparent;
    border: none;
    border-bottom: 1px solid #121820;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    min-height: 25px;
    max-height: 25px;
}
QLabel#commandRecordHint {
    background: transparent;
    color: #8b98a8;
    font-size: 12px;
    font-weight: 600;
}
QPlainTextEdit#commandRecordEditor {
    background: #05080c;
    color: #e8edf3;
    border: none;
    border-radius: 0px;
    padding: 8px 10px;
    selection-background-color: #303842;
    selection-color: #f8fbff;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 14px;
}
QPlainTextEdit#commandRecordEditor:focus {
    border: none;
}
QFrame#commandFindReplaceBar {
    background: #252526;
    border: 1px solid #3c3c3c;
    border-radius: 8px;
    min-height: 70px;
    max-height: 70px;
}
QLineEdit#commandFindInput,
QLineEdit#commandReplaceInput {
    background: #1e1e1e;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    color: #cccccc;
    padding: 4px 8px;
    min-height: 22px;
    selection-background-color: #264f78;
    selection-color: #ffffff;
}
QLineEdit#commandFindInput:focus,
QLineEdit#commandReplaceInput:focus {
    border-color: #007acc;
    background: #1e1e1e;
}
QToolButton#commandFindIconButton,
QToolButton#commandFindTextButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: #cccccc;
    padding: 3px 7px;
    min-height: 22px;
    font-weight: 600;
}
QToolButton#commandFindIconButton {
    min-width: 38px;
    max-width: 38px;
}
QToolButton#commandFindTextButton {
    min-width: 38px;
    max-width: 38px;
}
QToolButton#commandFindIconButton:hover,
QToolButton#commandFindTextButton:hover {
    background: #2a2d2e;
    border-color: #3c3c3c;
    color: #ffffff;
}
QFrame#commandRecordFooter {
    background: transparent;
    border: none;
    border-top: 1px solid #121820;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
    min-height: 27px;
    max-height: 27px;
}
QToolButton#commandTabButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    color: #8894a3;
    padding: 3px 9px;
    min-height: 21px;
    font-weight: 600;
}
QToolButton#commandTabButton[selected="true"] {
    background: #181d24;
    color: #f2f5f8;
}
QToolButton#commandTabButton:hover {
    background: #111820;
    color: #dce3eb;
}
QWidget#commandTabItem {
    background: transparent;
}
QToolButton#commandTabCloseButton {
    background: transparent;
    border: none;
    border-radius: 7px;
    color: #7f92a6;
    padding: 0px;
    margin: 0px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    font-size: 12px;
    font-weight: 700;
}
QToolButton#commandTabCloseButton[selected="true"] {
    color: #9fb0c2;
}
QToolButton#commandTabCloseButton:hover {
    background: #7f1d1d;
    color: #ffffff;
}
QToolButton#commandActionButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    color: #9aa7b6;
    padding: 3px 7px;
    font-weight: 600;
}
QToolButton#commandActionButton:hover {
    background: #171e26;
    border-color: #464e59;
    color: #f8fafc;
}
QToolButton#commandEnterModeButton {
    background: #111b25;
    border: 1px solid #2b4252;
    border-radius: 5px;
    color: #cbd5e1;
    padding: 1px 7px;
    min-height: 19px;
    font-size: 13px;
    font-weight: 700;
}
QToolButton#commandEnterModeButton[enterSends="true"] {
    background: #1b222b;
    border-color: #525b66;
    color: #f8fafc;
}
QToolButton#commandEnterModeButton:hover {
    background: #1b222b;
    border-color: #525b66;
    color: #f8fafc;
}
QToolButton#commandCollapseButton {
    background: transparent;
    border: 1px solid #243241;
    border-radius: 5px;
    color: #c3d3e4;
    padding: 3px 8px;
    font-weight: 700;
}
QToolButton#commandCollapseButton:hover {
    background: #181f27;
    border-color: #464e59;
    color: #f8fafc;
}
QToolButton#inspectorToggleButton {
    background: transparent;
    border: 1px solid #243241;
    border-radius: 6px;
    color: #9fb0c2;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 700;
}
QToolButton#inspectorToggleButton:hover {
    background: #181f27;
    border-color: #464e59;
    color: #f8fafc;
}
QToolButton#quickActionIconButton {
    background: #0b1016;
    border: 1px solid #202832;
    border-radius: 7px;
    color: #cbd5e1;
    padding: 0px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    font-size: 12px;
    font-weight: 700;
}
QToolButton#quickActionIconButton:hover {
    background: #171d24;
    border-color: #464e59;
    color: #f8fafc;
}
QToolButton#quickActionIconButton:disabled {
    color: #64748b;
    background: #090e13;
    border-color: #17212c;
}
QToolButton#quickDangerIconButton {
    background: #0b1016;
    border: 1px solid #202832;
    border-radius: 7px;
    color: #cbd5e1;
    padding: 0px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    font-size: 12px;
    font-weight: 700;
}
QToolButton#quickDangerIconButton:hover {
    background: #34181d;
    border-color: #8f2f3a;
    color: #fecaca;
}
QToolButton#quickDangerIconButton:disabled {
    color: #64748b;
    background: #090e13;
    border-color: #17212c;
}
QStatusBar {
    background: #0b1117;
    color: #96a6b8;
    border-top: 1px solid #253140;
}
QLabel#brandLabel {
    background: transparent;
    color: #f8fbff;
    font-size: 24px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#sectionTitle {
    background: transparent;
    color: #f8fbff;
    font-size: 16px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#sectionCopy {
    background: transparent;
    color: #96a6b8;
    font-size: 12px;
}
QLabel#navStatsText {
    background: transparent;
    color: #edf5ff;
    font-size: 14px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#navStatsText span {
    white-space: nowrap;
}
QLabel#inspectorText {
    background: transparent;
    color: #d5dee9;
    font-size: 13px;
    line-height: 1.55;
}
QLabel#statChip {
    border: 1px solid #283747;
    border-radius: 8px;
    padding: 8px 12px;
    background: #0f161d;
    color: #e5edf6;
}
QLabel#detailCard {
    border: 1px solid #273747;
    border-radius: 10px;
    padding: 16px;
    background: #0f161d;
    color: #e5edf6;
    line-height: 1.55;
}
QFrame#detailCard {
    border: 1px solid #273747;
    border-radius: 10px;
    background: #0f161d;
}
QLineEdit#detailValueInput {
    background: #0b1117;
    border: 1px solid #274052;
    border-radius: 7px;
    color: #dce6f1;
    padding: 4px 8px;
    font-weight: 700;
    selection-background-color: #2f4050;
    selection-color: #ffffff;
}
QLineEdit#detailValueInput:focus {
    border-color: #525b66;
}
QLabel#footerMetric {
    background: transparent;
    color: #96a6b8;
    font-size: 12px;
    font-weight: 600;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
    padding-left: 8px;
    padding-right: 8px;
}
QLabel#railTitle {
    background: transparent;
    color: #f8fbff;
    font-size: 15px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#railCopy {
    background: transparent;
    color: #96a6b8;
    font-size: 12px;
    line-height: 1.35;
}
QLabel#activeFilterText {
    background: transparent;
    color: #a8b5c4;
    font-size: 12px;
}
QLabel#activeFilterText {
    color: #c5d5e6;
}

/* Linear / Vercel dark minimal redesign overrides */
QWidget {
    background: #080808;
    color: #ededed;
    font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC";
    font-size: 12px;
}
QMainWindow {
    background: #080808;
}
QFrame#toolbarFrame,
QFrame#workspaceHeader,
QFrame#sessionToolbar,
QFrame#sessionInfoCard,
QFrame#sessionInputBar,
QFrame#navFilterBar,
QFrame#navStatsBar,
QFrame#myOccupancyCard,
QFrame#activeFilterBar,
QFrame#commandRecordDock,
QGroupBox {
    background: #0c0c0c;
    border: 1px solid #1a1a1a;
    border-radius: 8px;
}
QGroupBox {
    margin-top: 12px;
    padding-top: 8px;
    font-weight: 600;
    color: #ededed;
    font-size: 11px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    background: transparent;
}
QWidget#centerStage,
QWidget#inspectorRail,
QWidget#leftRail,
QWidget#deviceSessionPage,
QWidget#tabHeader,
QWidget#tabHeader[selected="true"],
QWidget#commandTabItem {
    background: transparent;
}
QScrollArea#inspectorScroll,
QScrollArea#inspectorScroll > QWidget > QWidget {
    background: transparent;
    border: none;
}
QFrame#sessionEmptyState {
    background: #0a0a0a;
    border: 1px dashed #262626;
    border-radius: 10px;
}
QLabel#sessionEmptyTitle {
    background: transparent;
    color: #ededed;
    font-size: 18px;
    font-weight: 600;
    font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC";
}
QLabel#sessionEmptyCopy {
    background: transparent;
    color: #808080;
    font-size: 12px;
    line-height: 1.6;
}
QGroupBox#deviceDetailCard,
QGroupBox#quickActionCard,
QGroupBox#authCard {
    background: #0e0e0e;
    border-color: #1a1a1a;
    border-radius: 8px;
}
QGroupBox#navShell {
    border-color: #1a1a1a;
    border-radius: 8px;
}
QFrame#navFilterBar,
QFrame#navStatsBar,
QFrame#sessionQuickBar,
QFrame#activeFilterBar {
    background: #0a0a0a;
    border: 1px solid #1e1e1e;
    border-radius: 8px;
}
QFrame#myOccupancyCard {
    background: #0c0c0c;
    border-color: #1a1a1a;
}
QWidget#leftSidebarShell {
    background: transparent;
}
QFrame#activityRail {
    background: #0a0a0a;
    border: 1px solid #1a1a1a;
    border-radius: 8px;
}
QToolButton#activityRailButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    color: #808080;
    padding: 0px;
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
}
QToolButton#activityRailButton:hover {
    background: #111111;
    border-color: #262626;
    color: #d0d0d0;
}
QToolButton#activityRailButton:checked {
    background: #141414;
    border-color: #333333;
    color: #ededed;
}
QToolButton#activityRailButton:disabled {
    background: transparent;
    border-color: transparent;
    color: #4d4d4d;
}
QFrame#connectionParamsHeader {
    background: transparent;
    border: none;
    min-height: 24px;
    max-height: 24px;
}
QFrame#connectionParamsPanel {
    background: transparent;
    border: none;
}
QFrame#connectionCompactRow {
    background: #0a0a0a;
    border: 1px solid #1a1a1a;
    border-radius: 6px;
}
QLabel#connectionKindLabel {
    background: transparent;
    color: #ededed;
    font-size: 11px;
    font-weight: 700;
}
QLabel#connectionMiniLabel {
    background: transparent;
    color: #808080;
    font-size: 10px;
    font-weight: 600;
}
QGroupBox#authCard QGroupBox {
    background: #0a0a0a;
    border: 1px solid #1a1a1a;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 12px;
}
QGroupBox#authCard QGroupBox::title {
    color: #a0a0a0;
    font-size: 10px;
    font-weight: 500;
}
QPushButton {
    background: #141414;
    border: 1px solid #262626;
    border-radius: 6px;
    padding: 6px 12px;
    color: #ededed;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover {
    background: #1a1a1a;
    border-color: #333333;
}
QPushButton:pressed {
    background: #111111;
}
QPushButton:disabled {
    color: #707070;
    background: #0e0e0e;
    border-color: #1a1a1a;
}
QPushButton#primaryButton {
    background: #5b6ef5;
    border-color: #5b6ef5;
    color: #fafafa;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background: #6d7ff7;
    border-color: #6d7ff7;
}
QPushButton#primaryButton:pressed {
    background: #4a5dd4;
}
QPushButton#primaryButton:disabled {
    background: #2a2a2a;
    border-color: #262626;
    color: #707070;
}
QPushButton#dangerButton {
    background: #2d1215;
    border-color: #5c2328;
    color: #f88b91;
}
QPushButton#dangerButton:hover {
    background: #3d181c;
    border-color: #732a30;
}
QPushButton#ghostButton,
QPushButton#compactGhostButton {
    background: transparent;
    border-color: #262626;
}
QPushButton#ghostButton:hover,
QPushButton#compactGhostButton:hover {
    background: #111111;
    border-color: #333333;
}
QPushButton#compactGhostButton {
    padding: 5px 8px;
    min-width: 44px;
}
QPushButton#filterToggleButton {
    background: #0e0e0e;
    border: 1px solid #262626;
    border-radius: 6px;
    color: #a0a0a0;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#filterToggleButton:hover {
    background: #161616;
    border-color: #333333;
    color: #ededed;
}
QPushButton#filterToggleButton:checked {
    background: #1a1a1a;
    border-color: #5b6ef5;
    color: #ededed;
}
QPushButton#filterToggleButton:disabled {
    background: #0e0e0e;
    border-color: #1a1a1a;
    color: #707070;
}
QLineEdit,
QComboBox,
QPlainTextEdit {
    background: #111111;
    border: 1px solid #262626;
    border-radius: 6px;
    padding: 6px 8px;
    color: #ededed;
    selection-background-color: #3a3f6b;
    selection-color: #ededed;
}
QLineEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus {
    border-color: #5b6ef5;
}
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QComboBox#sessionJumpCombo {
    background: #0e0e0e;
    border: 1px solid #262626;
    border-radius: 6px;
    color: #c0c0c0;
    padding: 4px 26px 4px 8px;
    min-height: 22px;
    font-size: 11px;
}
QComboBox#sessionJumpCombo:focus {
    border-color: #5b6ef5;
}
QComboBox#sessionJumpCombo:disabled {
    color: #707070;
    background: #0a0a0a;
    border-color: #1a1a1a;
}
QScrollBar:vertical {
    background: #0a0a0a;
    width: 8px;
    margin: 8px 2px 8px 2px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #262626;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #333333;
}
QScrollBar::handle:vertical:pressed {
    background: #404040;
}
QScrollBar::sub-line:vertical,
QScrollBar::add-line:vertical,
QScrollBar::sub-line:horizontal,
QScrollBar::add-line:horizontal {
    width: 0px;
    height: 0px;
    background: transparent;
    border: none;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
QScrollBar:horizontal {
    background: #0a0a0a;
    height: 10px;
    margin: 2px 6px 2px 6px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #262626;
    min-width: 28px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #333333;
}
QTableWidget {
    background: #0a0a0a;
    alternate-background-color: #0a0a0a;
    border: 1px solid #1a1a1a;
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: #3a3f6b;
    selection-color: #ededed;
}
QTableWidget::item {
    padding: 5px 8px;
    border-bottom: 1px solid #121212;
}
QTableWidget::item:selected {
    background: #3a3f6b;
    color: #ededed;
}
QTableWidget::item:hover {
    background: #161616;
}
QTableWidget::item:selected:hover {
    background: #3a3f6b;
    color: #ededed;
}
QTableWidget::item:focus {
    border: none;
    outline: none;
}
QTableWidget#deviceTable {
    border-color: #1a1a1a;
}
QHeaderView::section {
    background: #0a0a0a;
    color: #808080;
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid #1a1a1a;
    font-weight: 500;
    font-size: 11px;
}
QSplitter::handle {
    background: #080808;
}
QSplitter::handle:horizontal {
    width: 8px;
    margin: 8px 0;
}
QSplitter::handle:horizontal:hover {
    background: #141414;
}
QTabWidget::pane {
    border: 1px solid #1a1a1a;
    border-radius: 8px;
    background: #0a0a0a;
    top: -1px;
}
QTabWidget::tab-bar {
    left: 6px;
}
QTabBar::tab {
    background: #0a0a0a;
    color: #808080;
    border: 1px solid #1a1a1a;
    border-bottom-color: #1a1a1a;
    border-radius: 6px;
    padding: 3px 8px;
    min-width: 140px;
    min-height: 24px;
    margin-right: 2px;
    margin-top: 2px;
    font-size: 12px;
}
QTabBar::tab:selected {
    background: #141414;
    color: #ededed;
    border-color: #333333;
    border-bottom-color: #141414;
    margin-top: 0px;
    min-height: 26px;
}
QTabBar::tab:hover {
    color: #d0d0d0;
    background: #111111;
    border-color: #262626;
}
QTabWidget#deviceSessionTabs::pane {
    border: none;
    border-radius: 0px;
    background: transparent;
    top: 0px;
}
QTabWidget#deviceSessionTabs::tab-bar {
    left: 4px;
}
QTabWidget#deviceSessionTabs QTabBar::tab {
    background: #0a0a0a;
    border: 1px solid #1a1a1a;
    border-radius: 5px;
    color: #808080;
    min-width: 72px;
    min-height: 19px;
    padding: 2px 6px;
    margin-right: 2px;
    margin-top: 1px;
    font-size: 11px;
}
QTabWidget#deviceSessionTabs QTabBar::tab:selected {
    background: #141414;
    border-color: #333333;
    color: #ededed;
    min-height: 21px;
    margin-top: 0px;
}
QTabWidget#deviceSessionTabs QLabel#tabHeaderLabel {
    font-size: 11px;
}
QLabel#tabStatusDot {
    background: #606060;
    border-radius: 4px;
}
QLabel#tabStatusDot[connectionState="connecting"] {
    background: #f5a623;
}
QLabel#tabStatusDot[connectionState="connected"] {
    background: #3cc98e;
}
QLabel#tabStatusDot[connectionState="error"] {
    background: #f04f5a;
}
QLabel#tabHeaderLabel {
    background: transparent;
    color: #a0a0a0;
    font-size: 12px;
    font-weight: 500;
}
QLabel#tabHeaderLabel[selected="true"] {
    color: #ededed;
    font-weight: 500;
}
QToolButton#tabCloseButton {
    background: transparent;
    color: #707070;
    border: 1px solid transparent;
    border-radius: 5px;
    font-family: "Arial", "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 10px;
    font-weight: 700;
    padding: 0px;
    margin: 0px;
}
QToolButton#tabCloseButton[selected="true"] {
    color: #808080;
}
QToolButton#tabCloseButton:hover {
    background: #2d1215;
    color: #f88b91;
    border-color: #5c2328;
}
QPlainTextEdit#terminalLog {
    background: #06090d;
    color: #d6deeb;
    border: 1px solid #18212b;
    border-radius: 8px;
    font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 14px;
    font-weight: 400;
    padding: 16px 18px;
    selection-background-color: #334155;
    selection-color: #ededed;
}
QPlainTextEdit#terminalLog:focus {
    border-color: #3b4450;
}
QWidget#terminalLog {
    background: #06090d;
    color: #d6deeb;
    border: 1px solid #18212b;
    border-radius: 8px;
    font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 14px;
    font-weight: 400;
}
QWidget#terminalLog:focus {
    border-color: #3b4450;
}
QScrollBar#terminalScrollBar:vertical {
    background: #06090d;
    border: 0;
    width: 14px;
    margin: 2px;
}
QScrollBar#terminalScrollBar::handle:vertical {
    background: #2f3744;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar#terminalScrollBar::handle:vertical:hover {
    background: #475569;
}
QScrollBar#terminalScrollBar::add-line:vertical,
QScrollBar#terminalScrollBar::sub-line:vertical {
    height: 0;
}
QFrame#commandRecordDock {
    background: #080808;
    border: 1px solid #1a1a1a;
    border-top-color: #222222;
    border-radius: 8px;
}
QFrame#commandRecordResizeHandle {
    background: transparent;
    border: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QFrame#commandRecordResizeHandle:hover {
    background: #1a1a1a;
}
QFrame#commandRecordHintBar {
    background: transparent;
    border: none;
    border-bottom: 1px solid #121212;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    min-height: 22px;
    max-height: 22px;
}
QLabel#commandRecordHint {
    background: transparent;
    color: #808080;
    font-size: 11px;
    font-weight: 500;
}
QPlainTextEdit#commandRecordEditor {
    background: #080808;
    color: #ededed;
    border: none;
    border-radius: 0px;
    padding: 6px 8px;
    selection-background-color: #264f78;
    selection-color: #ededed;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 13px;
}
QPlainTextEdit#commandRecordEditor:focus {
    border: none;
}
QFrame#commandRecordFooter {
    background: transparent;
    border: none;
    border-top: 1px solid #121212;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    min-height: 24px;
    max-height: 24px;
}
QToolButton#commandTabButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #808080;
    padding: 3px 10px;
    min-height: 22px;
    font-weight: 500;
    font-size: 12px;
}
QToolButton#commandTabButton[selected="true"] {
    background: #161616;
    color: #ededed;
}
QToolButton#commandTabButton:hover {
    background: #111111;
    color: #d0d0d0;
}
QToolButton#commandTabCloseButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #707070;
    padding: 0px;
    margin: 0px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    font-size: 11px;
    font-weight: 700;
}
QToolButton#commandTabCloseButton[selected="true"] {
    color: #808080;
}
QToolButton#commandTabCloseButton:hover {
    background: #2d1215;
    color: #f88b91;
}
QToolButton#commandActionButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: #808080;
    padding: 2px 6px;
    font-weight: 500;
    font-size: 11px;
}
QToolButton#commandActionButton:hover {
    background: #141414;
    border-color: #333333;
    color: #ededed;
}
QToolButton#commandEnterModeButton {
    background: #0e0e0e;
    border: 1px solid #262626;
    border-radius: 4px;
    color: #a0a0a0;
    padding: 1px 6px;
    min-height: 16px;
    font-size: 12px;
    font-weight: 700;
}
QToolButton#commandEnterModeButton[enterSends="true"] {
    background: #161616;
    border-color: #5b6ef5;
    color: #ededed;
}
QToolButton#commandEnterModeButton:hover {
    background: #161616;
    border-color: #333333;
    color: #ededed;
}
QToolButton#commandCollapseButton,
QToolButton#inspectorToggleButton {
    background: transparent;
    border: 1px solid #262626;
    border-radius: 4px;
    color: #a0a0a0;
    padding: 2px 6px;
    font-weight: 600;
    font-size: 11px;
}
QToolButton#commandCollapseButton:hover,
QToolButton#inspectorToggleButton:hover {
    background: #141414;
    border-color: #333333;
    color: #ededed;
}
QToolButton#quickActionIconButton,
QToolButton#quickDangerIconButton {
    background: #0e0e0e;
    border: 1px solid #1e1e1e;
    border-radius: 5px;
    color: #a0a0a0;
    padding: 0px;
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    font-size: 11px;
    font-weight: 700;
}
QToolButton#quickActionIconButton:hover {
    background: #161616;
    border-color: #333333;
    color: #ededed;
}
QToolButton#quickActionIconButton:disabled,
QToolButton#quickDangerIconButton:disabled {
    color: #707070;
    background: #0a0a0a;
    border-color: #1a1a1a;
}
QToolButton#quickDangerIconButton:hover {
    background: #2d1215;
    border-color: #5c2328;
    color: #f88b91;
}
QStatusBar {
    background: #0c0c0c;
    color: #808080;
    border-top: 1px solid #1a1a1a;
    font-size: 11px;
}
QLabel#brandLabel,
QLabel#sectionTitle,
QLabel#railTitle,
QLabel#navStatsText,
QLabel#footerMetric {
    background: transparent;
    font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC";
}
QLabel#brandLabel {
    color: #ededed;
    font-size: 20px;
    font-weight: 700;
}
QLabel#sectionTitle,
QLabel#railTitle {
    color: #ededed;
    font-size: 14px;
    font-weight: 600;
}
QLabel#sectionCopy,
QLabel#railCopy {
    background: transparent;
    color: #808080;
    font-size: 11px;
    line-height: 1.35;
}
QLabel#navStatsText {
    color: #ededed;
    font-size: 12px;
    font-weight: 600;
}
QLabel#inspectorText {
    background: transparent;
    color: #d0d0d0;
    font-size: 12px;
    line-height: 1.5;
}
QLabel#statChip {
    border: 1px solid #1a1a1a;
    border-radius: 6px;
    padding: 6px 10px;
    background: #0e0e0e;
    color: #ededed;
}
QLabel#detailCard {
    border: 1px solid #1a1a1a;
    border-radius: 8px;
    padding: 12px;
    background: #0e0e0e;
    color: #ededed;
    line-height: 1.5;
}
QFrame#detailCard {
    border: 1px solid #1a1a1a;
    border-radius: 8px;
    background: #0e0e0e;
}
QLineEdit#detailValueInput {
    background: #111111;
    border: 1px solid #262626;
    border-radius: 6px;
    color: #c0c0c0;
    padding: 4px 8px;
    font-weight: 600;
    selection-background-color: #3a3f6b;
    selection-color: #ededed;
}
QLineEdit#detailValueInput:focus {
    border-color: #5b6ef5;
}
QLabel#footerMetric {
    color: #808080;
    font-size: 11px;
    font-weight: 500;
    padding-left: 6px;
    padding-right: 6px;
}
QLabel#activeFilterText {
    background: transparent;
    color: #c0c0c0;
    font-size: 11px;
}
"""
