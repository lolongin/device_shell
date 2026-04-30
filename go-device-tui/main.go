package main

import (
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/x/ansi"
	"github.com/mattn/go-runewidth"
)

const (
	allDomains = "All Domains"
	allStatus  = "All Statuses"
	allCPUs    = "All CPUs"
)

var (
	statusOrder      = []string{StatusOccupied, StatusIdle, StatusPipeline, StatusOther}
	rowNumberPattern = regexp.MustCompile(`\b(\d{4})\b`)

	pageStyle = lipgloss.NewStyle().
			Padding(1, 2).
			Foreground(lipgloss.Color("#E8F0FF")).
			Background(lipgloss.Color("#08111F"))

	headerStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#F4F8FF")).
			Background(lipgloss.Color("#14304D")).
			Padding(0, 1).
			Bold(true)

	subheadStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#89A7C7"))

	bannerStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("#1A3554")).
			Background(lipgloss.Color("#0A1422")).
			Padding(0, 1)

	panelStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("#213A58")).
			Background(lipgloss.Color("#0D1726")).
			Padding(0, 1)

	activePanelStyle = panelStyle.Copy().
				BorderForeground(lipgloss.Color("#69C0FF")).
				Background(lipgloss.Color("#0F1B2C"))

	titleStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#A6D7FF")).
			Bold(true)

	activeTitleStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#DDF2FF")).
				Bold(true)

	mutedStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#7D93AD"))

	sectionLabelStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#7F9CBC")).
				Background(lipgloss.Color("#0D1726")).
				Bold(true)

	valueStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#F2F7FF")).
			Background(lipgloss.Color("#0D1726"))

	detailValueStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#E8F2FF")).
				Background(lipgloss.Color("#0D1726"))

	notesStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#D7E6F7")).
			Background(lipgloss.Color("#0D1726")).
			Italic(true)

	selectedRowStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#FFFFFF")).
				Background(lipgloss.Color("#183653")).
				Bold(true)

	secondarySelectedRowStyle = lipgloss.NewStyle().
					Foreground(lipgloss.Color("#CFE7FF")).
					Background(lipgloss.Color("#10233B"))

	focusBadgeStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#08111F")).
			Background(lipgloss.Color("#69C0FF")).
			Bold(true).
			Padding(0, 1)

	pillStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#DCEBFF")).
			Background(lipgloss.Color("#10233B")).
			Padding(0, 1)

	activePillStyle = pillStyle.Copy().
			Foreground(lipgloss.Color("#FFFFFF")).
			Background(lipgloss.Color("#1F4D78")).
			Bold(true)

	searchPillStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#EAF4FF")).
			Background(lipgloss.Color("#0F2236")).
			Padding(0, 1)

	footerStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#CFE4FF")).
			Background(lipgloss.Color("#10233B")).
			Padding(0, 1)

	statsVisibleStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#F4F8FF")).
				Background(lipgloss.Color("#1A3554")).
				Bold(true).
				Padding(0, 1)

	statsOccupiedStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#082112")).
				Background(lipgloss.Color("#41D68A")).
				Bold(true).
				Padding(0, 1)

	statsIdleStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#081A28")).
			Background(lipgloss.Color("#69C0FF")).
			Bold(true).
			Padding(0, 1)

	statsPipelineStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#2A1900")).
				Background(lipgloss.Color("#FFC56E")).
				Bold(true).
				Padding(0, 1)

	statsOtherStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#211032")).
			Background(lipgloss.Color("#C89DFF")).
			Bold(true).
			Padding(0, 1)

	statusStyles = map[string]lipgloss.Style{
		StatusOccupied: lipgloss.NewStyle().Foreground(lipgloss.Color("#41D68A")),
		StatusIdle:     lipgloss.NewStyle().Foreground(lipgloss.Color("#69C0FF")),
		StatusPipeline: lipgloss.NewStyle().Foreground(lipgloss.Color("#FFC56E")),
		StatusOther:    lipgloss.NewStyle().Foreground(lipgloss.Color("#C89DFF")),
	}
)

type focusArea int

const (
	focusDevices focusArea = iota
	focusOwned
	focusSearch
	focusDomain
	focusStatus
	focusCPU
)

type execFinishedMsg struct {
	message string
	err     error
}

type uiLayout struct {
	contentWidth int
	headerHeight int
	footerHeight int
	mainHeight   int
	bottomHeight int
	leftWidth    int
	rightWidth   int
	leftStart    int
	mainTop      int
	bottomTop    int
}

type model struct {
	width  int
	height int

	devices         []Device
	deviceIndexByID map[string]int

	filterText   string
	filterDomain string
	filterStatus string
	filterCPU    string

	visibleDevices []int
	ownedDevices   []int

	selectedDeviceID string
	showPassword     bool
	statusMessage    string

	focus focusArea

	deviceCursor int
	ownedCursor  int

	domainOptions []string
	statusOptions []string
	cpuOptions    []string

	lastClickPanel string
	lastClickID    string
	lastClickAt    time.Time

	lastMouseButton  tea.MouseButton
	lastMouseAction  tea.MouseAction
	lastMouseX       int
	lastMouseY       int
	lastMouseEventAt time.Time
}

func main() {
	devices := sampleDevices()

	m := model{
		width:           120,
		height:          40,
		devices:         devices,
		deviceIndexByID: buildDeviceIndex(devices),
		filterDomain:    allDomains,
		filterStatus:    allStatus,
		filterCPU:       allCPUs,
		statusMessage:   "Bubble Tea version ready",
		focus:           focusDevices,
		domainOptions:   append([]string{allDomains}, uniqueDomains(devices)...),
		statusOptions:   append([]string{allStatus}, statusOrder...),
		cpuOptions:      append([]string{allCPUs}, uniqueCPUs(devices)...),
	}
	m.refreshFilteredView()

	program := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion(), tea.WithInputTTY(), tea.WithFPS(20))
	if _, err := program.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "device-tui-go failed: %v\n", err)
		os.Exit(1)
	}
}

func (m model) Init() tea.Cmd {
	return nil
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case execFinishedMsg:
		if msg.err != nil {
			m.statusMessage = "command failed: " + msg.err.Error()
		} else if msg.message != "" {
			m.statusMessage = msg.message
		}
		return m, nil

	case tea.KeyMsg:
		if m.focus == focusSearch {
			switch msg.String() {
			case "tab":
				m.focus = nextFocus(m.focus, 1)
				return m, nil
			case "shift+tab":
				m.focus = nextFocus(m.focus, -1)
				return m, nil
			case "esc":
				m.focus = focusDevices
				return m, nil
			case "backspace":
				if len([]rune(m.filterText)) > 0 {
					runes := []rune(m.filterText)
					m.filterText = string(runes[:len(runes)-1])
					m.refreshFilteredView()
				}
				return m, nil
			}

			if msg.Type == tea.KeyRunes {
				m.filterText += msg.String()
				m.refreshFilteredView()
				return m, nil
			}
			return m, nil
		}

		switch msg.String() {
		case "ctrl+c", "q":
			return m, tea.Quit
		case "/":
			m.focus = focusSearch
			return m, nil
		case "tab":
			m.focus = nextFocus(m.focus, 1)
			return m, nil
		case "shift+tab":
			m.focus = nextFocus(m.focus, -1)
			return m, nil
		case "p":
			m.showPassword = !m.showPassword
			if m.showPassword {
				m.statusMessage = "Password visible"
			} else {
				m.statusMessage = "Password hidden"
			}
			return m, nil
		case "o":
			m.toggleOccupySelected()
			return m, nil
		case "s":
			return m, m.connectSelected("ssh", false)
		case "S":
			return m, m.connectSelected("ssh", true)
		case "t":
			return m, m.connectSelected("telnet", false)
		case "T":
			return m, m.connectSelected("telnet", true)
		case "up", "k":
			m.moveCursor(-1)
			return m, nil
		case "down", "j":
			m.moveCursor(1)
			return m, nil
		case "left", "h":
			m.adjustFilter(-1)
			return m, nil
		case "right", "l", "enter":
			m.adjustFilter(1)
			return m, nil
		}

	case tea.MouseMsg:
		if m.shouldHandlePrimaryClick(msg) {
			m.handleMouseClick(msg.X, msg.Y)
			return m, nil
		}
	}

	return m, nil
}

func (m model) View() string {
	return m.renderScreen()
}

func (m model) renderScreen() string {
	if m.width == 0 || m.height == 0 {
		return "loading..."
	}

	layout := m.computeLayout()
	header := m.renderHeader(layout.contentWidth)

	main := lipgloss.JoinHorizontal(
		lipgloss.Top,
		m.renderDevicePanel(layout.leftWidth, layout.mainHeight),
		" ",
		m.renderDetailPanel(layout.rightWidth, layout.mainHeight),
	)

	bottom := lipgloss.JoinHorizontal(
		lipgloss.Top,
		m.renderOwnedPanel(layout.leftWidth, layout.bottomHeight),
		" ",
		m.renderHelpPanel(layout.rightWidth, layout.bottomHeight),
	)

	footer := m.renderFooter(layout.contentWidth)

	return pageStyle.Width(m.width).Height(m.height).Render(
		lipgloss.JoinVertical(lipgloss.Left, header, "", main, " ", bottom, "", footer),
	)
}

func (m model) renderHeader(width int) string {
	title := headerStyle.Render(" Device Control Deck ")
	subtitle := subheadStyle.Render("Bubble Tea dashboard for discovery, filtering, claiming, and jump-in access")
	stats := m.renderStatsBar(width - 2)
	filters := m.renderFilterBar(width - 2)
	return bannerStyle.Width(width).Render(strings.Join([]string{
		title,
		subtitle,
		"",
		stats,
		filters,
	}, "\n"))
}

func (m model) renderFooter(width int) string {
	selected := "No device selected"
	if device, ok := m.selectedDevice(); ok {
		selected = fmt.Sprintf("%s 路 %s 路 %s 路 %s", device.Name, device.Domain, device.CPU, device.Status)
	}

	focusText := map[focusArea]string{
		focusDevices: "Focus Devices",
		focusOwned:   "Focus My Occupancy",
		focusSearch:  "Focus Search",
		focusDomain:  "Focus Domain Filter",
		focusStatus:  "Focus Status Filter",
		focusCPU:     "Focus CPU Filter",
	}[m.focus]

	text := trimDisplay(focusText+"   |   "+selected, width-2)
	return footerStyle.Width(width).Render(text)
}

func (m *model) refreshFilteredView() {
	m.visibleDevices = m.visibleDevices[:0]
	m.ownedDevices = m.ownedDevices[:0]
	needle := strings.ToLower(strings.TrimSpace(m.filterText))

	for idx := range m.devices {
		device := m.devices[idx]
		if device.Owner == CurrentUser && device.Status == StatusOccupied {
			m.ownedDevices = append(m.ownedDevices, idx)
		}
		if m.filterDomain != allDomains && device.Domain != m.filterDomain {
			continue
		}
		if m.filterStatus != allStatus && device.Status != m.filterStatus {
			continue
		}
		if m.filterCPU != allCPUs && device.CPU != m.filterCPU {
			continue
		}
		if needle != "" && !strings.Contains(searchText(device), needle) {
			continue
		}
		m.visibleDevices = append(m.visibleDevices, idx)
	}

	m.ensureSelection()
	m.syncCursors()
}

func (m *model) ensureSelection() {
	if len(m.visibleDevices) == 0 {
		m.selectedDeviceID = ""
		m.deviceCursor = 0
		m.ownedCursor = 0
		return
	}
	for _, idx := range m.visibleDevices {
		if m.devices[idx].ID == m.selectedDeviceID {
			return
		}
	}
	m.selectedDeviceID = m.devices[m.visibleDevices[0]].ID
}

func (m *model) syncCursors() {
	m.deviceCursor = indexForID(m.selectedDeviceID, m.visibleDevices, m.devices)
	if m.deviceCursor < 0 {
		m.deviceCursor = 0
	}

	m.ownedCursor = indexForID(m.selectedDeviceID, m.ownedDevices, m.devices)
	if m.ownedCursor < 0 {
		m.ownedCursor = 0
	}
}

func (m *model) moveCursor(delta int) {
	switch m.focus {
	case focusDevices:
		if len(m.visibleDevices) == 0 {
			return
		}
		m.deviceCursor = clamp(m.deviceCursor+delta, 0, len(m.visibleDevices)-1)
		m.selectedDeviceID = m.devices[m.visibleDevices[m.deviceCursor]].ID
		m.syncCursors()
	case focusOwned:
		if len(m.ownedDevices) == 0 {
			return
		}
		m.ownedCursor = clamp(m.ownedCursor+delta, 0, len(m.ownedDevices)-1)
		m.selectedDeviceID = m.devices[m.ownedDevices[m.ownedCursor]].ID
		m.syncCursors()
	}
}

func (m *model) adjustFilter(step int) {
	switch m.focus {
	case focusDomain:
		m.filterDomain = cycleOption(m.domainOptions, m.filterDomain, step)
		m.statusMessage = "Domain: " + m.filterDomain
	case focusStatus:
		m.filterStatus = cycleOption(m.statusOptions, m.filterStatus, step)
		m.statusMessage = "Status: " + m.filterStatus
	case focusCPU:
		m.filterCPU = cycleOption(m.cpuOptions, m.filterCPU, step)
		m.statusMessage = "CPU: " + m.filterCPU
	default:
		return
	}
	m.refreshFilteredView()
}

func (m *model) toggleOccupySelected() {
	device, ok := m.selectedDevice()
	if !ok {
		return
	}

	switch {
	case device.Owner == CurrentUser && device.Status == StatusOccupied:
		device.Owner = ""
		device.Status = StatusIdle
		m.statusMessage = "Released " + device.Name
	case device.Owner == "" && device.Status == StatusIdle:
		device.Owner = CurrentUser
		device.Status = StatusOccupied
		m.statusMessage = "Claimed " + device.Name
	default:
		m.statusMessage = device.Name + " is " + device.Status
	}

	m.refreshFilteredView()
}

func (m *model) releaseSelected() {
	device, ok := m.selectedDevice()
	if !ok {
		return
	}

	switch {
	case device.Owner == CurrentUser && device.Status == StatusOccupied:
		device.Owner = ""
		device.Status = StatusIdle
		m.statusMessage = "Released " + device.Name
	default:
		m.statusMessage = device.Name + " is " + device.Status
	}

	m.refreshFilteredView()
}

func (m *model) handleMouseClick(x, y int) {
	hit, row, ok := m.hitTestListRow(x, y)
	if !ok {
		m.statusMessage = fmt.Sprintf("Mouse %d,%d did not hit a device row", x, y)
		return
	}

	switch hit {
	case "devices":
		if row >= 0 && row < len(m.visibleDevices) {
			m.focus = focusDevices
			m.deviceCursor = row
			deviceID := m.devices[m.visibleDevices[row]].ID
			m.selectedDeviceID = deviceID
			m.syncCursors()
			m.statusMessage = "Selected " + m.devices[m.visibleDevices[row]].Name
			if m.isDoubleClick("devices", deviceID) {
				m.toggleOccupySelected()
			}
		}
	case "owned":
		if row >= 0 && row < len(m.ownedDevices) {
			m.focus = focusOwned
			m.ownedCursor = row
			deviceID := m.devices[m.ownedDevices[row]].ID
			m.selectedDeviceID = deviceID
			m.syncCursors()
			m.statusMessage = "Selected " + m.devices[m.ownedDevices[row]].Name
			if m.isDoubleClick("owned", deviceID) {
				m.releaseSelected()
			}
		}
	}
}

func (m *model) isDoubleClick(panel, deviceID string) bool {
	now := time.Now()
	double := m.lastClickPanel == panel && m.lastClickID == deviceID && now.Sub(m.lastClickAt) <= 450*time.Millisecond
	m.lastClickPanel = panel
	m.lastClickID = deviceID
	m.lastClickAt = now
	return double
}

func (m *model) shouldHandlePrimaryClick(msg tea.MouseMsg) bool {
	if msg.Button != tea.MouseButtonLeft {
		return false
	}

	if msg.Action != tea.MouseActionPress && msg.Action != tea.MouseActionRelease {
		return false
	}

	now := time.Now()
	if runtime.GOOS == "windows" &&
		m.lastMouseButton == msg.Button &&
		m.lastMouseX == msg.X &&
		m.lastMouseY == msg.Y &&
		now.Sub(m.lastMouseEventAt) <= 80*time.Millisecond {
		m.lastMouseAction = msg.Action
		m.lastMouseEventAt = now
		return false
	}

	m.lastMouseButton = msg.Button
	m.lastMouseAction = msg.Action
	m.lastMouseX = msg.X
	m.lastMouseY = msg.Y
	m.lastMouseEventAt = now
	return true
}

func (m model) hitTestListRow(x, y int) (panel string, row int, ok bool) {
	layout := m.computeLayout()
	leftHitStart := max(0, layout.leftStart-8)
	leftHitEnd := minInt(m.width, layout.leftStart+layout.leftWidth+8)

	if x >= leftHitStart && x < leftHitEnd {
		if y >= layout.mainTop && y < layout.mainTop+layout.mainHeight {
			if row, ok := m.hitRowFromRenderedScreen(y, layout.leftStart, layout.leftWidth, len(m.visibleDevices)); ok {
				return "devices", row, true
			}
		}
		if y >= layout.bottomTop && y < layout.bottomTop+layout.bottomHeight {
			if row, ok := m.hitRowFromRenderedScreen(y, layout.leftStart, layout.leftWidth, len(m.ownedDevices)); ok {
				return "owned", row, true
			}
		}
	}

	return "", 0, false
}

func (m model) hitRowFromRenderedScreen(y, leftStart, leftWidth, totalRows int) (int, bool) {
	if totalRows == 0 {
		return 0, false
	}

	lines := strings.Split(m.renderScreen(), "\n")
	if len(lines) == 0 {
		return 0, false
	}

	searchStart := max(0, y-2)
	searchEnd := minInt(len(lines)-1, y+2)
	for offset := 0; offset <= 2; offset++ {
		candidates := []int{y - offset}
		if offset > 0 {
			candidates = append(candidates, y+offset)
		}
		for _, lineIndex := range candidates {
			if lineIndex < searchStart || lineIndex > searchEnd {
				continue
			}
			line := ansi.Strip(lines[lineIndex])
			segment := ansi.Cut(line, leftStart, leftStart+leftWidth)
			matches := rowNumberPattern.FindStringSubmatch(segment)
			if len(matches) != 2 {
				continue
			}
			n, err := strconv.Atoi(matches[1])
			if err != nil {
				continue
			}
			row := n - 1
			if row >= 0 && row < totalRows {
				return row, true
			}
		}
	}

	return 0, false
}

func (m model) connectSelected(proto string, external bool) tea.Cmd {
	device, ok := m.selectedDevice()
	if !ok {
		return nil
	}

	var (
		command string
		args    []string
	)

	switch proto {
	case "ssh":
		command = "ssh"
		args = []string{fmt.Sprintf("%s@%s", device.Username, device.SSHIP)}
	case "telnet":
		command = "telnet"
		args = []string{device.TelnetIP}
	default:
		return nil
	}

	if _, err := exec.LookPath(command); err != nil {
		return func() tea.Msg {
			return execFinishedMsg{message: command + " command not found"}
		}
	}

	if external {
		return func() tea.Msg {
			err := launchExternalTerminal(device.Name, command, args...)
			if err != nil {
				return execFinishedMsg{err: err}
			}
			return execFinishedMsg{message: "Opened " + strings.ToUpper(proto) + " window: " + device.Name}
		}
	}

	cmd := exec.Command(command, args...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	return tea.ExecProcess(cmd, func(err error) tea.Msg {
		if err != nil {
			return execFinishedMsg{err: err}
		}
		return execFinishedMsg{message: strings.ToUpper(proto) + " closed: " + device.Name}
	})
}

func (m model) selectedDevice() (*Device, bool) {
	idx, ok := m.deviceIndexByID[m.selectedDeviceID]
	if !ok || idx < 0 || idx >= len(m.devices) {
		return nil, false
	}
	return &m.devices[idx], true
}

func (m model) renderDevicePanel(width, height int) string {
	start, end := visibleRange(m.deviceCursor, len(m.visibleDevices), max(1, height-5))
	header := panelHeader("Device Directory", m.focus == focusDevices || m.focus == focusSearch || m.focus == focusDomain || m.focus == focusStatus || m.focus == focusCPU)
	lines := []string{
		header,
		mutedStyle.Render("Browse the filtered fleet and move with arrow keys or j/k"),
		mutedStyle.Render(m.renderRangeSummary(start, end, len(m.visibleDevices))),
		"",
	}
	lines = append(lines, m.renderTableLines(m.visibleDevices, m.deviceCursor, width-4, height-len(lines)-2, m.focus == focusDevices)...)
	return renderPanel(lines, width, height, m.focus == focusDevices || m.focus == focusSearch || m.focus == focusDomain || m.focus == focusStatus || m.focus == focusCPU)
}

func (m model) renderOwnedPanel(width, height int) string {
	start, end := visibleRange(m.ownedCursor, len(m.ownedDevices), max(1, height-5))
	header := panelHeader("My Occupancy", m.focus == focusOwned)
	summary := m.renderRangeSummary(start, end, len(m.ownedDevices))
	if len(m.ownedDevices) == 0 {
		summary = "No claimed devices yet"
	}
	lines := []string{
		header,
		mutedStyle.Render("Current user: " + CurrentUser),
		mutedStyle.Render(summary),
		"",
	}
	lines = append(lines, m.renderTableLines(m.ownedDevices, m.ownedCursor, width-4, height-len(lines)-2, m.focus == focusOwned)...)
	return renderPanel(lines, width, height, m.focus == focusOwned)
}

func (m model) renderDetailPanel(width, height int) string {
	lines := []string{
		titleStyle.Render("Device Detail"),
		mutedStyle.Render("Access, ownership, hardware, placement"),
		"",
	}
	lines = append(lines, m.renderDetailLines(width-4)...)
	return renderPanel(lines, width, height, false)
}

func (m model) renderHelpPanel(width, height int) string {
	lines := []string{
		titleStyle.Render("Control Guide"),
		"",
		sectionLabelStyle.Render("Status"),
		valueStyle.Render(m.statusMessage),
		"",
		sectionLabelStyle.Render("Navigation"),
		mutedStyle.Render("Tab switch focus  / search  鈫戔啌 move  鈫愨啋 cycle filters"),
		sectionLabelStyle.Render("Actions"),
		mutedStyle.Render("Double-click list row to claim/release  o keyboard toggle  p password"),
		mutedStyle.Render("s/t connect  S/T new terminal  q quit"),
	}
	return renderPanel(lines, width, height, false)
}

func (m model) renderRangeSummary(start, end, total int) string {
	if total == 0 {
		return "0 shown"
	}
	return fmt.Sprintf("Showing %d-%d of %d", start+1, end, total)
}

func (m model) renderStatsBar(width int) string {
	counts := map[string]int{
		StatusOccupied: 0,
		StatusIdle:     0,
		StatusPipeline: 0,
		StatusOther:    0,
	}
	for _, idx := range m.visibleDevices {
		counts[m.devices[idx].Status]++
	}

	items := []string{
		statsVisibleStyle.Render(fmt.Sprintf("Visible %d", len(m.visibleDevices))),
		statsOccupiedStyle.Render(fmt.Sprintf("Occupied %d", counts[StatusOccupied])),
		statsIdleStyle.Render(fmt.Sprintf("Idle %d", counts[StatusIdle])),
		statsPipelineStyle.Render(fmt.Sprintf("Pipeline %d", counts[StatusPipeline])),
		statsOtherStyle.Render(fmt.Sprintf("Other %d", counts[StatusOther])),
	}
	return trimDisplay(strings.Join(items, " "), width)
}

func (m model) renderFilterBar(width int) string {
	searchValue := m.filterText
	if searchValue == "" {
		searchValue = "search devices"
	}
	if m.focus == focusSearch {
		searchValue += "_"
	}

	items := []string{
		searchFilterPill(searchValue, m.focus == focusSearch),
		filterPill("Domain", shortFilterValue(m.filterDomain, allDomains, "All"), m.focus == focusDomain),
		filterPill("Status", shortFilterValue(m.filterStatus, allStatus, "All"), m.focus == focusStatus),
		filterPill("CPU", shortFilterValue(m.filterCPU, allCPUs, "All"), m.focus == focusCPU),
	}
	return trimDisplay(strings.Join(items, " "), width)
}

func (m model) renderTableLines(rows []int, cursor, width, height int, active bool) []string {
	if len(rows) == 0 {
		return []string{mutedStyle.Render("No devices match the current filter.")}
	}

	header := padColumns(
		[]string{" ", "#", "Name", "Domain", "CPU", "Status"},
		[]int{1, 4, 21, 10, 8, 12},
	)
	lines := []string{titleStyle.Render(header)}
	start, end := visibleRange(cursor, len(rows), max(1, height-2))

	for row := start; row < end; row++ {
		device := m.devices[rows[row]]
		marker := " "
		if m.selectedDeviceID == device.ID {
			marker = "*"
		}
		if active && row == cursor {
			marker = ">"
		}
		line := padColumns(
			[]string{
				marker,
				fmt.Sprintf("%04d", row+1),
				device.Name,
				device.Domain,
				device.CPU,
				device.Status,
			},
			[]int{1, 4, 21, 10, 8, 12},
		)
		if active && row == cursor {
			lines = append(lines, selectedRowStyle.Render(trimDisplay(line, width)))
		} else if m.selectedDeviceID == device.ID {
			lines = append(lines, secondarySelectedRowStyle.Render(trimDisplay(line, width)))
		} else {
			lines = append(lines, trimDisplay(line, width))
		}
	}

	return lines
}

func (m model) renderDetailLines(width int) []string {
	if m.selectedDeviceID == "" {
		return []string{mutedStyle.Render("No devices match the current filter.")}
	}

	device, ok := m.selectedDevice()
	if !ok {
		return []string{mutedStyle.Render("Selected device not found.")}
	}

	owner := device.Owner
	if owner == "" {
		owner = "Unassigned"
	}
	password := strings.Repeat("*", max(8, len(device.Password)))
	if m.showPassword {
		password = device.Password
	}

	statusText := renderStatus(device.Status)
	lines := []string{
		titleStyle.Render(device.Name),
		mutedStyle.Render(fmt.Sprintf("%s | %s | %s", device.ID, device.Domain, device.DeviceType)),
		"",
		sectionLabelStyle.Render("Connection"),
		renderKV("SSH", device.SSHIP),
		renderKV("Telnet", device.TelnetIP),
		sectionLabelStyle.Render("Access"),
		renderKV("User", device.Username),
		renderKV("Pass", password),
		sectionLabelStyle.Render("Ownership"),
		renderKV("Status", statusText),
		renderKV("Owner", owner),
		sectionLabelStyle.Render("Hardware"),
		renderKV("CPU", device.CPU),
		renderKV("Vendor", device.Vendor),
		renderKV("Model", device.Model),
		renderKV("Version", device.Version),
		sectionLabelStyle.Render("Placement"),
		renderKV("Site", device.Site),
		renderKV("Rack", device.Rack),
		"",
		sectionLabelStyle.Render("Notes"),
	}
	lines = append(lines, wrapStyledText(device.Notes, width, notesStyle)...)
	for idx, line := range lines {
		lines[idx] = trimDisplay(line, width)
	}
	return lines
}

func uniqueDomains(devices []Device) []string {
	set := make(map[string]struct{})
	for _, device := range devices {
		set[device.Domain] = struct{}{}
	}
	values := make([]string, 0, len(set))
	for value := range set {
		values = append(values, value)
	}
	sort.Strings(values)
	return values
}

func uniqueCPUs(devices []Device) []string {
	set := make(map[string]struct{})
	for _, device := range devices {
		set[device.CPU] = struct{}{}
	}
	values := make([]string, 0, len(set))
	for value := range set {
		values = append(values, value)
	}
	sort.Strings(values)
	return values
}

func searchText(device Device) string {
	parts := []string{
		device.ID,
		device.Name,
		device.Domain,
		device.DeviceType,
		device.CPU,
		device.Status,
		device.Vendor,
		device.Model,
		device.Site,
		device.Rack,
	}
	return strings.ToLower(strings.Join(parts, " "))
}

func launchExternalTerminal(title, command string, args ...string) error {
	fullCommand := strings.TrimSpace(command + " " + strings.Join(args, " "))
	switch runtime.GOOS {
	case "windows":
		wtArgs := []string{"new-tab", "--title", title, "powershell", "-NoExit", "-Command", fullCommand}
		if _, err := exec.LookPath("wt"); err == nil {
			return exec.Command("wt", wtArgs...).Start()
		}
		psCommand := fmt.Sprintf("Start-Process powershell -ArgumentList '-NoExit','-Command','%s'", strings.ReplaceAll(fullCommand, "'", "''"))
		return exec.Command("powershell", "-NoProfile", "-Command", psCommand).Start()
	default:
		if _, err := exec.LookPath("x-terminal-emulator"); err == nil {
			return exec.Command("x-terminal-emulator", "-e", fullCommand).Start()
		}
		if _, err := exec.LookPath("xterm"); err == nil {
			return exec.Command("xterm", "-e", fullCommand).Start()
		}
		return fmt.Errorf("no terminal launcher found")
	}
}

func nextFocus(current focusArea, step int) focusArea {
	order := []focusArea{focusDevices, focusOwned, focusSearch, focusDomain, focusStatus, focusCPU}
	for idx, value := range order {
		if value == current {
			return order[(idx+step+len(order))%len(order)]
		}
	}
	return focusDevices
}

func cycleOption(options []string, current string, step int) string {
	if len(options) == 0 {
		return current
	}
	for idx, option := range options {
		if option == current {
			return options[(idx+step+len(options))%len(options)]
		}
	}
	return options[0]
}

func indexForID(id string, rows []int, devices []Device) int {
	for idx, row := range rows {
		if devices[row].ID == id {
			return idx
		}
	}
	return -1
}

func buildDeviceIndex(devices []Device) map[string]int {
	index := make(map[string]int, len(devices))
	for i := range devices {
		index[devices[i].ID] = i
	}
	return index
}

func (m model) computeLayout() uiLayout {
	contentWidth := max(60, m.width-8)
	headerHeight := lipgloss.Height(m.renderHeader(contentWidth))
	footerHeight := 1

	leftWidth := max(50, contentWidth*3/5)
	rightWidth := max(28, contentWidth-leftWidth-1)

	pageVerticalPadding := 2
	gaps := 3
	availableHeight := m.height - pageVerticalPadding - headerHeight - footerHeight - gaps
	if availableHeight < 12 {
		availableHeight = 12
	}

	mainHeight := availableHeight * 2 / 3
	bottomHeight := availableHeight - mainHeight

	if mainHeight < 12 {
		mainHeight = 12
		bottomHeight = max(5, availableHeight-mainHeight)
	}
	if bottomHeight < 5 {
		bottomHeight = 5
		mainHeight = max(7, availableHeight-bottomHeight)
	}

	pageTopPadding := 1
	mainTop := pageTopPadding + headerHeight + 1
	bottomTop := mainTop + mainHeight + 1

	return uiLayout{
		contentWidth: contentWidth,
		headerHeight: headerHeight,
		footerHeight: footerHeight,
		mainHeight:   mainHeight,
		bottomHeight: bottomHeight,
		leftWidth:    leftWidth,
		rightWidth:   rightWidth,
		leftStart:    2,
		mainTop:      mainTop,
		bottomTop:    bottomTop,
	}
}

func visibleRange(cursor, total, size int) (int, int) {
	if total <= size {
		return 0, total
	}
	start := cursor - size/2
	if start < 0 {
		start = 0
	}
	end := start + size
	if end > total {
		end = total
		start = end - size
	}
	return start, end
}

func panelWithFocus(active bool) lipgloss.Style {
	if active {
		return activePanelStyle.Copy()
	}
	return panelStyle.Copy()
}

func renderStatus(status string) string {
	style, ok := statusStyles[status]
	if !ok {
		return status
	}
	return style.Render(status)
}

func panelHeader(title string, active bool) string {
	if active {
		return lipgloss.JoinHorizontal(lipgloss.Center, activeTitleStyle.Render(title), " ", focusBadgeStyle.Render("FOCUS"))
	}
	return titleStyle.Render(title)
}

func filterPill(label, value string, active bool) string {
	style := pillStyle
	if active {
		style = activePillStyle
	}
	return style.Render(label + " " + value)
}

func searchFilterPill(value string, active bool) string {
	style := searchPillStyle
	if active {
		style = activePillStyle
	}
	return style.Render("Search " + value)
}

func shortFilterValue(value, allValue, replacement string) string {
	if value == allValue {
		return replacement
	}
	return value
}

func renderKV(label, value string) string {
	return sectionLabelStyle.Render(padDisplay(label, 8)+" ") + detailValueStyle.Render(value)
}

func wrapStyledText(value string, width int, style lipgloss.Style) []string {
	if width <= 0 {
		return []string{""}
	}
	words := strings.Fields(value)
	if len(words) == 0 {
		return []string{style.Render("")}
	}

	lines := []string{}
	current := ""
	for _, word := range words {
		next := word
		if current != "" {
			next = current + " " + word
		}
		if runewidth.StringWidth(next) > width && current != "" {
			lines = append(lines, style.Render(current))
			current = word
			continue
		}
		current = next
	}
	if current != "" {
		lines = append(lines, style.Render(current))
	}
	return lines
}

func renderPanel(lines []string, width, height int, active bool) string {
	contentWidth := max(1, width-4)
	contentHeight := max(1, height-2)
	normalized := make([]string, 0, len(lines))
	for _, line := range lines {
		normalized = append(normalized, trimDisplay(line, contentWidth))
	}
	if len(normalized) > contentHeight {
		normalized = normalized[:contentHeight]
	}
	for len(normalized) < contentHeight {
		normalized = append(normalized, "")
	}
	return panelWithFocus(active).
		Width(width).
		Height(height).
		Render(strings.Join(normalized, "\n"))
}

func padColumns(values []string, widths []int) string {
	parts := make([]string, 0, len(values))
	for idx, value := range values {
		parts = append(parts, padDisplay(value, widths[idx]))
	}
	return strings.Join(parts, " ")
}

func padDisplay(value string, width int) string {
	trimmed := trimDisplay(value, width)
	padding := width - runewidth.StringWidth(trimmed)
	if padding < 0 {
		padding = 0
	}
	return trimmed + strings.Repeat(" ", padding)
}

func trimDisplay(value string, width int) string {
	if width <= 0 {
		return ""
	}
	if runewidth.StringWidth(value) <= width {
		return value
	}
	runes := []rune(value)
	result := ""
	for _, r := range runes {
		next := result + string(r)
		if runewidth.StringWidth(next+"...") > width {
			break
		}
		result = next
	}
	if result == "" {
		return ""
	}
	return result + "..."
}

func clamp(value, minValue, maxValue int) int {
	if value < minValue {
		return minValue
	}
	if value > maxValue {
		return maxValue
	}
	return value
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
