from __future__ import annotations

from ._sample_data import STATUS_IDLE, STATUS_OCCUPIED, STATUS_OTHER, STATUS_PIPELINE


STATUS_COLORS = {
    STATUS_IDLE: "#22c55e",
    STATUS_OCCUPIED: "#fbbf24",
    STATUS_PIPELINE: "#60a5fa",
    STATUS_OTHER: "#718096",
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
QPushButton#compactGhostButton:checked {
    background: #102019;
    border-color: #2f7d5b;
    color: #d1fae5;
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
QFrame#commandSuggestionBar {
    background: #070b10;
    border-top: 1px solid #161d26;
}
QToolButton#commandSuggestionButton {
    background: #0b1016;
    border: 1px solid #243044;
    border-radius: 6px;
    color: #cbd5e1;
    padding: 0px 8px;
    min-height: 22px;
    max-height: 22px;
    font-size: 11px;
    font-weight: 700;
}
QToolButton#commandSuggestionButton:hover {
    background: #152033;
    border-color: #4f7cff;
    color: #f8fafc;
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
QToolButton#autoResponseMenuButton,
QToolButton#autoResponseRuleButton {
    background: #0b1016;
    border: 1px solid #202832;
    border-radius: 7px;
    color: #cbd5e1;
    padding: 0px 8px;
    min-height: 28px;
    max-height: 28px;
    font-size: 12px;
    font-weight: 700;
}
QToolButton#autoResponseMenuButton:hover,
QToolButton#autoResponseRuleButton:hover {
    background: #171d24;
    border-color: #464e59;
    color: #f8fafc;
}
QToolButton#autoResponseRuleButton:checked {
    background: #102019;
    border-color: #2f7d5b;
    color: #d1fae5;
}
QToolButton#autoResponseRuleButton[waitingForInput="true"]:checked {
    background: #101915;
    border-color: #2b6049;
    color: #b7e4cf;
}
QToolButton#autoResponseRuleButton:!checked {
    color: #7f8b99;
}
QFrame#autoResponseRuleBar {
    background: transparent;
    border: none;
}
QLabel#autoResponseOverflowLabel {
    color: #9fb0c2;
    font-size: 12px;
    font-weight: 700;
    padding: 0px 4px;
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
QPushButton#compactGhostButton:checked {
    background: #102019;
    border-color: #2f7d5b;
    color: #d1fae5;
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
QFrame#commandSuggestionBar {
    background: #070707;
    border-top: 1px solid #1c1c1c;
}
QToolButton#commandSuggestionButton {
    background: #0e0e0e;
    border: 1px solid #2b2b2b;
    border-radius: 5px;
    color: #bdbdbd;
    padding: 0px 7px;
    min-height: 22px;
    max-height: 22px;
    font-size: 11px;
    font-weight: 700;
}
QToolButton#commandSuggestionButton:hover {
    background: #161616;
    border-color: #4f7cff;
    color: #ededed;
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
QToolButton#autoResponseMenuButton,
QToolButton#autoResponseRuleButton {
    background: #0e0e0e;
    border: 1px solid #1e1e1e;
    border-radius: 5px;
    color: #a0a0a0;
    padding: 0px 7px;
    min-height: 26px;
    max-height: 26px;
    font-size: 11px;
    font-weight: 700;
}
QToolButton#autoResponseMenuButton:hover,
QToolButton#autoResponseRuleButton:hover {
    background: #161616;
    border-color: #333333;
    color: #ededed;
}
QToolButton#autoResponseRuleButton:checked {
    background: #102019;
    border-color: #2f7d5b;
    color: #d1fae5;
}
QToolButton#autoResponseRuleButton[waitingForInput="true"]:checked {
    background: #101915;
    border-color: #2b6049;
    color: #b7e4cf;
}
QToolButton#autoResponseRuleButton:!checked {
    color: #707070;
}
QFrame#autoResponseRuleBar {
    background: transparent;
    border: none;
}
QLabel#autoResponseOverflowLabel {
    color: #808080;
    font-size: 11px;
    font-weight: 700;
    padding: 0px 3px;
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
QCheckBox {
    background: transparent;
    color: #ededed;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #5b6ef5;
    border-radius: 3px;
    background: #111111;
}
QCheckBox::indicator:hover {
    border-color: #8d9aff;
    background: #181818;
}
QCheckBox::indicator:checked {
    background: #5b6ef5;
    border-color: #8d9aff;
}
QCheckBox::indicator:disabled {
    background: #0a0a0a;
    border-color: #333333;
}

/* Unified workspace overlays and native popup surfaces */
QFrame#commandFindReplaceBar {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 10px;
}
QLineEdit#commandFindInput,
QLineEdit#commandReplaceInput {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 7px;
    color: #f8fafc;
    selection-background-color: #24324a;
    selection-color: #f8fafc;
}
QLineEdit#commandFindInput:focus,
QLineEdit#commandReplaceInput:focus {
    background: #08101d;
    border-color: #60a5fa;
}
QLabel#commandFindCount {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 7px;
    color: #a7b4c7;
    font-size: 11px;
    padding: 2px 6px;
}
QToolButton#commandFindIconButton,
QToolButton#commandFindTextButton {
    color: #a7b4c7;
    border-radius: 6px;
}
QToolButton#commandFindIconButton:hover,
QToolButton#commandFindTextButton:hover {
    background: #172236;
    border-color: #334155;
    color: #f8fafc;
}
QMenu {
    background: #0f172a;
    color: #e5edf6;
    border: 1px solid #334155;
    border-radius: 9px;
    padding: 6px;
}
QMenu::item {
    min-width: 168px;
    padding: 7px 28px 7px 10px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #163326;
    color: #d8fff0;
}
QMenu::item:disabled {
    color: #64748b;
}
QMenu::separator {
    height: 1px;
    background: #243244;
    margin: 5px 7px;
}
QMenu::indicator {
    width: 14px;
    height: 14px;
    left: 8px;
}
QToolTip {
    background: #111c2f;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 8px;
}
QStatusBar {
    background: #08101d;
    color: #8fa0b7;
    border-top: 1px solid #243244;
}
QCheckBox::indicator {
    border-color: #3b7a5d;
    background: #08101d;
}
QCheckBox::indicator:hover {
    border-color: #22c55e;
    background: #102019;
}
QCheckBox::indicator:checked {
    background: #22c55e;
    border-color: #4ade80;
}
QFrame#temporaryFormCard {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 12px;
}
QFrame#temporaryProtocolCard {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 12px;
}
QFrame#temporaryProtocolCard:hover {
    background: #0f172a;
    border-color: #334155;
}
QFrame#temporaryProtocolCard[protocol="telnet"],
QFrame#temporaryProtocolCard[protocol="ssh"],
QFrame#temporaryProtocolCard[protocol="serial"] {
    color: #d8e4f5;
}
QFrame#temporaryDeviceCard {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 12px;
}
QFrame#temporaryDeviceCard:hover {
    background: #111c2f;
    border-color: #334155;
}
QLabel#temporaryCardTitle {
    background: transparent;
    color: #f8fafc;
    font-weight: 800;
}
QLabel#temporaryCardEndpoint,
QLabel#temporaryCardNotes {
    background: transparent;
    color: #a7b4c7;
    font-size: 11px;
}
QLabel#temporaryCardNotes {
    color: #718096;
}
QLabel#temporaryProtocolPill {
    background: #102019;
    border: 1px solid #22c55e;
    border-radius: 999px;
    color: #d8fff0;
    font-size: 10px;
    font-weight: 700;
    padding: 1px 6px;
}
QFrame#temporaryDeviceCard QPushButton#compactGhostButton {
    background: #08101d;
    border-color: #243244;
}
QFrame#temporaryDeviceCard QPushButton#compactGhostButton:hover {
    background: #172236;
    border-color: #334155;
}
QFrame#temporaryDeviceCard QPushButton#dangerButton {
    background: #2d1215;
    border-color: #5c2328;
    color: #fecaca;
}
QFrame#temporaryDeviceCard QPushButton#dangerButton:hover {
    background: #3d181c;
    border-color: #f87171;
}
QFrame#transferConfigCard {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 12px;
}
QFrame#transferStatusCard {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 12px;
}
QFrame#transferStatusCard[state="running"] {
    background: #071611;
    border-color: #22c55e;
}
QFrame#transferStatusCard[state="stopped"] {
    background: #0f172a;
    border-color: #243244;
}
QLabel#activeFilterText[surface="transferStatus"] {
    background: transparent;
    border: none;
    padding: 0px;
    color: #d8e4f5;
}
QLabel#transferEndpointText {
    color: #a7b4c7;
    font-family: "Fira Code", "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 11px;
}
QLabel#transferHintText {
    background: transparent;
    border: none;
    padding: 0px;
    color: #a7b4c7;
    font-size: 11px;
}
QPlainTextEdit#transferLogOutput {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 12px;
    color: #d6deeb;
    padding: 8px;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
}
QPlainTextEdit#transferLogOutput:focus {
    border-color: #60a5fa;
}

/* Terminal workspace shell */
QTabWidget#sessionTabs::pane {
    background: #020617;
    border: 1px solid #1e293b;
    border-radius: 12px;
    top: -1px;
}
QTabWidget#sessionTabs::tab-bar {
    left: 8px;
}
QTabWidget#sessionTabs QTabBar::tab {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 9px;
    color: #a7b4c7;
    min-width: 132px;
    min-height: 26px;
    padding: 4px 10px;
    margin-right: 4px;
    margin-top: 3px;
}
QTabWidget#sessionTabs QTabBar::tab:selected {
    background: #111c2f;
    border-color: #334155;
    border-bottom-color: #111c2f;
    color: #f8fafc;
    margin-top: 0px;
    min-height: 29px;
}
QTabWidget#sessionTabs QTabBar::tab:hover {
    background: #172236;
    border-color: #334155;
    color: #e5edf6;
}
QTabWidget#deviceSessionTabs::pane {
    background: #020617;
    border: none;
    border-radius: 0px;
    top: 0px;
}
QTabWidget#deviceSessionTabs QTabBar::tab {
    background: #08101d;
    border: 1px solid #1e293b;
    border-radius: 7px;
    color: #8fa0b7;
    min-width: 70px;
    min-height: 21px;
    padding: 3px 7px;
    margin-right: 3px;
    margin-top: 2px;
}
QTabWidget#deviceSessionTabs QTabBar::tab:selected {
    background: #0f172a;
    border-color: #334155;
    color: #f8fafc;
    min-height: 23px;
    margin-top: 0px;
}
QLabel#tabStatusDot[connectionState="connected"] {
    background: #22c55e;
}
QLabel#tabStatusDot[connectionState="connecting"] {
    background: #fbbf24;
}
QLabel#tabStatusDot[connectionState="error"] {
    background: #fb7185;
}
QLabel#tabHeaderLabel {
    color: #a7b4c7;
}
QLabel#tabHeaderLabel[selected="true"] {
    color: #f8fafc;
}
QToolButton#tabCloseButton:hover {
    background: #3d181c;
    border-color: #f87171;
    color: #fecaca;
}
QFrame#sessionQuickBar {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 12px;
}
QFrame#sessionQuickRestoreBar {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 10px;
}
QFrame#sessionJumpResizeHandle {
    background: #172236;
    border: 1px solid #243244;
    border-radius: 3px;
}
QFrame#sessionJumpResizeHandle:hover {
    background: #1e3a5f;
    border-color: #60a5fa;
}
QFrame#terminalNavigationResizeHandle {
    background: #172236;
    border: 1px solid #243244;
    border-radius: 3px;
}
QFrame#terminalNavigationResizeHandle:hover {
    background: #1e3a5f;
    border-color: #60a5fa;
}
QLabel#terminalOpsLabel {
    background: transparent;
    color: #22c55e;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 0 6px;
}
QLabel#terminalSessionCountPill {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 999px;
    color: #a7b4c7;
    font-size: 11px;
    font-weight: 700;
    padding: 4px 8px;
}
QFrame#sessionQuickBar QComboBox#sessionJumpCombo {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 8px;
    color: #d8e4f5;
    padding: 5px 28px 5px 10px;
}
QFrame#sessionQuickBar QComboBox#sessionJumpCombo:focus {
    border-color: #60a5fa;
}
QToolButton#sessionQuickRestoreButton {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 8px;
    color: #d8e4f5;
    font-weight: 700;
    padding: 4px 10px;
}
QToolButton#sessionQuickRestoreButton:hover {
    background: #163326;
    border-color: #22c55e;
    color: #d8fff0;
}
QFrame#commandRecordDock {
    background: #020617;
    border: 1px solid #243244;
    border-radius: 12px;
}
QFrame#commandRecordResizeHandle:hover {
    background: #111c2f;
}
QFrame#commandRecordHintBar,
QFrame#commandRecordFooter,
QFrame#commandSuggestionBar {
    background: #0f172a;
    border-color: #243244;
}
QFrame#commandRecordHintBar {
    border-bottom: 1px solid #243244;
}
QFrame#commandRecordFooter {
    border-top: 1px solid #243244;
}
QPlainTextEdit#commandRecordEditor {
    background: #020617;
    color: #f8fafc;
    selection-background-color: #1e3a5f;
}
QPlainTextEdit#commandRecordEditor:focus {
    background: #020617;
}
QToolButton#quickActionIconButton,
QToolButton#quickDangerIconButton,
QToolButton#autoResponseMenuButton,
QToolButton#autoResponseRuleButton,
QToolButton#commandSuggestionButton,
QToolButton#commandActionButton,
QToolButton#commandEnterModeButton,
QToolButton#commandCollapseButton,
QToolButton#commandTabButton {
    background: #08101d;
    border: 1px solid #243244;
    color: #a7b4c7;
}
QToolButton#quickActionIconButton:hover,
QToolButton#autoResponseMenuButton:hover,
QToolButton#autoResponseRuleButton:hover,
QToolButton#commandSuggestionButton:hover,
QToolButton#commandActionButton:hover,
QToolButton#commandEnterModeButton:hover,
QToolButton#commandCollapseButton:hover,
QToolButton#commandTabButton:hover {
    background: #163326;
    border-color: #22c55e;
    color: #d8fff0;
}
QToolButton#commandTabButton[selected="true"],
QToolButton#commandEnterModeButton[enterSends="true"],
QToolButton#autoResponseRuleButton:checked {
    background: #102019;
    border-color: #22c55e;
    color: #d8fff0;
}
QToolButton#quickActionIconButton:disabled,
QToolButton#quickDangerIconButton:disabled {
    background: #08101d;
    border-color: #172236;
    color: #526176;
}
QToolButton#quickDangerIconButton:hover {
    background: #3d181c;
    border-color: #f87171;
    color: #fecaca;
}

/* Left drawer native surfaces */
QGroupBox#navShell,
QGroupBox#deviceDetailCard,
QGroupBox#quickActionCard,
QGroupBox#authCard {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 12px;
    margin-top: 10px;
}
QGroupBox#navShell::title,
QGroupBox#deviceDetailCard::title,
QGroupBox#quickActionCard::title,
QGroupBox#authCard::title {
    color: #d8e4f5;
    font-weight: 700;
    padding: 0px 6px;
}
QFrame#activityRail {
    background: #020617;
    border: 1px solid #1e293b;
    border-radius: 12px;
}
QToolButton#activityRailButton:hover {
    background: #102019;
    border-color: #22c55e;
    color: #d8fff0;
}
QToolButton#activityRailButton:checked {
    background: #163326;
    border-color: #22c55e;
    color: #f8fafc;
}
QFrame#connectionParamsPanel {
    background: transparent;
    border: none;
}
QFrame#connectionCompactRow[surface="connectionProtocolCard"] {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 12px;
}
QFrame#connectionCompactRow[surface="connectionProtocolCard"]:hover {
    background: #0f172a;
    border-color: #334155;
}
QFrame#connectionCompactRow QLabel#connectionKindLabel {
    color: #f8fafc;
    font-size: 12px;
    font-weight: 800;
}
QFrame#connectionCompactRow QLabel#connectionMiniLabel {
    color: #8fa0b7;
    font-size: 10px;
    font-weight: 700;
}
QFrame#connectionCompactRow QLineEdit[connectionField="host"],
QFrame#connectionCompactRow QLineEdit[connectionField="username"],
QFrame#connectionCompactRow QLineEdit[connectionField="password"] {
    background: #020617;
    border: 1px solid #1e293b;
    border-radius: 8px;
    color: #f8fafc;
    padding: 5px 8px;
}
QFrame#connectionCompactRow QLineEdit[connectionField="host"]:focus,
QFrame#connectionCompactRow QLineEdit[connectionField="username"]:focus,
QFrame#connectionCompactRow QLineEdit[connectionField="password"]:focus {
    border-color: #60a5fa;
}
QPushButton#primaryButton {
    background: #15803d;
    border: 1px solid #22c55e;
    color: #f0fdf4;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background: #16a34a;
    border-color: #4ade80;
}
QPushButton#primaryButton:pressed {
    background: #166534;
}
QPushButton#ghostButton,
QPushButton#compactGhostButton {
    background: #08101d;
    border: 1px solid #243244;
    color: #a7b4c7;
}
QPushButton#ghostButton:hover,
QPushButton#compactGhostButton:hover {
    background: #172236;
    border-color: #334155;
    color: #f8fafc;
}

/* Workspace dialogs */
QDialog#workspaceDialog,
QMessageBox {
    background: #020617;
    color: #f8fafc;
}
QDialog#workspaceDialog QLabel,
QMessageBox QLabel {
    background: transparent;
    color: #d8e4f5;
}
QDialog#workspaceDialog QFrame#dialogFormCard {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 12px;
}
QDialog#workspaceDialog QLineEdit,
QDialog#workspaceDialog QComboBox,
QDialog#workspaceDialog QSpinBox {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 8px;
    color: #f8fafc;
    padding: 5px 8px;
    selection-background-color: #24324a;
    selection-color: #f8fafc;
}
QDialog#workspaceDialog QLineEdit:focus,
QDialog#workspaceDialog QComboBox:focus,
QDialog#workspaceDialog QSpinBox:focus {
    border-color: #60a5fa;
}
QDialog#workspaceDialog QCheckBox {
    color: #d8e4f5;
}
QDialogButtonBox#workspaceDialogButtons {
    background: #0f172a;
    border-top: 1px solid #243244;
    padding: 8px;
}
QDialogButtonBox#workspaceDialogButtons QPushButton {
    min-width: 92px;
    background: #08101d;
    border: 1px solid #243244;
    color: #a7b4c7;
}
QDialogButtonBox#workspaceDialogButtons QPushButton:hover {
    background: #172236;
    border-color: #334155;
    color: #f8fafc;
}
QDialogButtonBox#workspaceDialogButtons QPushButton[text="OK"],
QDialogButtonBox#workspaceDialogButtons QPushButton[text="确定"] {
    background: #15803d;
    border-color: #22c55e;
    color: #f0fdf4;
}

/* Data tables and scrollbars */
QTableWidget {
    background: #020617;
    alternate-background-color: #020617;
    border: 1px solid #243244;
    border-radius: 12px;
    gridline-color: transparent;
    selection-background-color: #24324a;
    selection-color: #f8fafc;
}
QTableWidget::item {
    padding: 6px 9px;
    border-bottom: 1px solid #111c2f;
}
QTableWidget::item:selected,
QTableWidget::item:selected:hover {
    background: #24324a;
    color: #f8fafc;
}
QTableWidget::item:hover {
    background: #111c2f;
}
QTableWidget#deviceTable {
    border-color: #243244;
}
QHeaderView::section {
    background: #0f172a;
    color: #a7b4c7;
    padding: 6px 9px;
    border: none;
    border-bottom: 1px solid #243244;
    font-weight: 700;
    font-size: 11px;
}
QScrollBar:vertical {
    background: #08101d;
    width: 10px;
    margin: 8px 2px 8px 2px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #334155;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #475569;
}
QScrollBar:horizontal {
    background: #08101d;
    height: 10px;
    margin: 2px 6px 2px 6px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: #334155;
    min-width: 28px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background: #475569;
}

/* Native workspace foundation */
QMainWindow,
QWidget#centerStage,
QWidget#leftSidebarShell,
QFrame#activityRail {
    background: #020617;
    color: #f8fafc;
}
QGroupBox {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 12px;
    color: #f8fafc;
}
QGroupBox::title {
    color: #a7b4c7;
}
QLineEdit,
QComboBox,
QTextEdit,
QPlainTextEdit {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 8px;
    color: #f8fafc;
    selection-background-color: #24324a;
    selection-color: #f8fafc;
}
QLineEdit:focus,
QComboBox:focus,
QTextEdit:focus,
QPlainTextEdit:focus {
    border-color: #60a5fa;
    background: #08101d;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background: #0f172a;
    border: 1px solid #334155;
    color: #f8fafc;
    selection-background-color: #24324a;
    selection-color: #f8fafc;
    outline: none;
}
QPushButton {
    background: #08101d;
    border: 1px solid #334155;
    border-radius: 8px;
    color: #f8fafc;
    padding: 8px 12px;
}
QPushButton:hover {
    background: #111c2f;
    border-color: #60a5fa;
}
QPushButton:pressed {
    background: #0f172a;
    border-color: #22c55e;
}
QPushButton:disabled {
    background: #08101d;
    border-color: #243244;
    color: #718096;
}
QPushButton#primaryButton,
QPushButton[connectionAction="primary"] {
    background: #15803d;
    border-color: #22c55e;
    color: #f0fdf4;
}
QPushButton#primaryButton:hover,
QPushButton[connectionAction="primary"]:hover {
    background: #16a34a;
    border-color: #4ade80;
}
QPushButton#dangerButton {
    background: #2d1215;
    border-color: #5c2328;
    color: #fecaca;
}
QPushButton#dangerButton:hover {
    background: #3d181c;
    border-color: #f87171;
}
QPushButton#ghostButton,
QPushButton#compactGhostButton {
    background: #08101d;
    border-color: #243244;
    color: #a7b4c7;
}
QPushButton#ghostButton:hover,
QPushButton#compactGhostButton:hover {
    background: #172236;
    border-color: #334155;
    color: #f8fafc;
}
QSplitter::handle {
    background: #020617;
}
QSplitter::handle:hover {
    background: #243244;
}
QMenu {
    background: #0f172a;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 9px;
    padding: 6px;
}
QMenu::item:selected {
    background: #163326;
    color: #d8fff0;
}
QMenu::item:disabled {
    color: #718096;
}
QMenu#workspaceContextMenu {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 7px;
}
QMenu#workspaceContextMenu::item {
    min-width: 176px;
    padding: 8px 30px 8px 12px;
    border-radius: 7px;
}
QMenu#workspaceContextMenu::item:selected {
    background: #163326;
    color: #d8fff0;
}
QMenu#workspaceContextMenu::item:disabled {
    color: #a7b4c7;
}
QMenu#workspaceContextMenu::separator {
    height: 1px;
    background: #243244;
    margin: 6px 8px;
}
QToolTip {
    background: #111c2f;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 8px;
}
QStatusBar {
    background: #08101d;
    color: #a7b4c7;
    border-top: 1px solid #243244;
}

/* Terminal render surface foundation */
QPlainTextEdit#terminalLog,
QWidget#terminalLog,
QWidget#terminalPlaceholder,
QWebEngineView#terminalWebView {
    background: #020617;
    color: #f8fafc;
    border: 1px solid #243244;
    border-radius: 12px;
    font-family: "Cascadia Mono", "JetBrains Mono", "Fira Code", "Consolas", "Microsoft YaHei UI";
    selection-background-color: #24324a;
    selection-color: #f8fafc;
}
QPlainTextEdit#terminalLog:focus,
QWidget#terminalLog:focus {
    border-color: #60a5fa;
}
QScrollBar#terminalScrollBar:vertical {
    background: #08101d;
    border: 0;
    width: 10px;
    margin: 8px 2px 8px 2px;
    border-radius: 5px;
}
QScrollBar#terminalScrollBar::handle:vertical {
    background: #334155;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar#terminalScrollBar::handle:vertical:hover {
    background: #475569;
}

/* OLED workspace final cascade */
QWidget {
    background: #020617;
    color: #f8fafc;
    font-family: "Fira Sans", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI";
}
QLabel#brandLabel,
QLabel#sectionTitle,
QLabel#railTitle,
QLabel#navStatsText,
QLabel#footerMetric,
QLabel#tabHeaderLabel[selected="true"] {
    background: transparent;
    color: #f8fafc;
}
QLabel#sectionCopy,
QLabel#railCopy,
QLabel#activeFilterText,
QLabel#footerMetric,
QLabel#commandRecordHint,
QLabel#autoResponseOverflowLabel,
QLabel#tabHeaderLabel {
    background: transparent;
    color: #a7b4c7;
}
QFrame#activityRail,
QFrame#commandRecordDock,
QFrame#commandSuggestionBar,
QFrame#commandRecordFooter,
QFrame#commandRecordHintBar,
QFrame#sessionQuickBar,
QFrame#activeFilterBar,
QFrame#navFilterBar,
QFrame#navStatsBar,
QFrame#myOccupancyCard,
QFrame#connectionCompactRow,
QFrame#detailCard,
QLabel#detailCard,
QLabel#statChip {
    background: #0f172a;
    border: 1px solid #243244;
    color: #f8fafc;
}
QFrame#commandRecordDock,
QFrame#detailCard,
QLabel#detailCard {
    border-radius: 12px;
}
QToolButton#activityRailButton,
QToolButton#quickActionIconButton,
QToolButton#quickDangerIconButton,
QToolButton#autoResponseMenuButton,
QToolButton#autoResponseRuleButton,
QToolButton#commandSuggestionButton,
QToolButton#commandTabButton,
QToolButton#commandActionButton,
QToolButton#commandEnterModeButton,
QToolButton#commandCollapseButton,
QToolButton#inspectorToggleButton {
    background: #08101d;
    border: 1px solid #243244;
    color: #a7b4c7;
}
QToolButton#activityRailButton:hover,
QToolButton#quickActionIconButton:hover,
QToolButton#autoResponseMenuButton:hover,
QToolButton#autoResponseRuleButton:hover,
QToolButton#commandSuggestionButton:hover,
QToolButton#commandTabButton:hover,
QToolButton#commandActionButton:hover,
QToolButton#commandEnterModeButton:hover,
QToolButton#commandCollapseButton:hover,
QToolButton#inspectorToggleButton:hover {
    background: #111c2f;
    border-color: #60a5fa;
    color: #f8fafc;
}
QToolButton#activityRailButton:checked,
QToolButton#autoResponseRuleButton:checked,
QToolButton#commandEnterModeButton[enterSends="true"],
QToolButton#commandTabButton[selected="true"] {
    background: #163326;
    border-color: #22c55e;
    color: #d8fff0;
}
QToolButton#quickDangerIconButton:hover,
QToolButton#commandTabCloseButton:hover,
QToolButton#tabCloseButton:hover {
    background: #2d1215;
    border-color: #f87171;
    color: #fecaca;
}
QPlainTextEdit#commandRecordEditor,
QLineEdit#detailValueInput {
    background: #020617;
    border: 1px solid #243244;
    color: #f8fafc;
    selection-background-color: #24324a;
    selection-color: #f8fafc;
    font-family: "Fira Code", "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
}
QPlainTextEdit#commandRecordEditor:focus,
QLineEdit#detailValueInput:focus {
    border-color: #60a5fa;
}
QLabel#tabStatusDot {
    background: #718096;
}
QLabel#tabStatusDot[connectionState="connecting"] {
    background: #fbbf24;
}
QLabel#tabStatusDot[connectionState="connected"] {
    background: #22c55e;
}
QLabel#tabStatusDot[connectionState="error"] {
    background: #f87171;
}
QCheckBox {
    background: transparent;
    color: #f8fafc;
}
QCheckBox::indicator {
    background: #08101d;
    border: 1px solid #334155;
}
QCheckBox::indicator:hover {
    border-color: #60a5fa;
    background: #111c2f;
}
QCheckBox::indicator:checked {
    background: #22c55e;
    border-color: #4ade80;
}
"""
