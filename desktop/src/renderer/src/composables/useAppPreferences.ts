import { ref } from 'vue'

export type ThemeMode = 'dark' | 'light'
export type SessionTabLayout = 'top' | 'side'

type FeedbackTarget = {
  notice: string
  error: string
}

const THEME_KEY = 'odyterm.desktop-v2.theme'
const ALWAYS_ON_TOP_KEY = 'odyterm.desktop-v2.always-on-top'
const SESSION_TAB_LAYOUT_KEY = 'odyterm.desktop-v2.session-tab-layout'
const SESSION_TAB_RAIL_COLLAPSED_KEY = 'odyterm.desktop-v2.session-tab-rail-collapsed'
const NAVIGATOR_DETAIL_COLLAPSED_KEY = 'odyterm.desktop-v2.navigator-detail-collapsed'

export function useAppPreferences(feedback: FeedbackTarget) {
  const themeMode = ref<ThemeMode>(localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark')
  const alwaysOnTop = ref(localStorage.getItem(ALWAYS_ON_TOP_KEY) === '1')
  const sessionTabLayout = ref<SessionTabLayout>(
    localStorage.getItem(SESSION_TAB_LAYOUT_KEY) === 'side' ? 'side' : 'top'
  )
  const sessionTabRailCollapsed = ref(
    localStorage.getItem(SESSION_TAB_RAIL_COLLAPSED_KEY) === '1'
  )
  const navigatorDetailCollapsed = ref(
    localStorage.getItem(NAVIGATOR_DETAIL_COLLAPSED_KEY) === '1'
  )

  function applyRendererTheme(mode: ThemeMode): void {
    themeMode.value = mode
    document.documentElement.dataset.theme = mode
    document.documentElement.style.colorScheme = mode
    localStorage.setItem(THEME_KEY, mode)
    void window.desktopApi?.setNativeTheme(mode).catch(() => {
      // The renderer theme remains usable if the preload bridge is unavailable.
    })
  }

  async function setAlwaysOnTop(enabled: boolean, announce = true): Promise<void> {
    try {
      alwaysOnTop.value = await window.desktopApi.setAlwaysOnTop(enabled)
      localStorage.setItem(ALWAYS_ON_TOP_KEY, alwaysOnTop.value ? '1' : '0')
      if (announce) feedback.notice = alwaysOnTop.value ? '窗口已置顶' : '窗口已取消置顶'
      feedback.error = ''
    } catch (cause) {
      feedback.error = cause instanceof Error ? cause.message : String(cause)
    }
  }

  function toggleAlwaysOnTop(): void {
    void setAlwaysOnTop(!alwaysOnTop.value)
  }

  function toggleTheme(): void {
    applyRendererTheme(themeMode.value === 'dark' ? 'light' : 'dark')
  }

  function setSessionTabLayout(layout: SessionTabLayout): void {
    sessionTabLayout.value = layout
    localStorage.setItem(SESSION_TAB_LAYOUT_KEY, layout)
  }

  function setSessionTabRailCollapsed(collapsed: boolean): void {
    sessionTabRailCollapsed.value = collapsed
    localStorage.setItem(SESSION_TAB_RAIL_COLLAPSED_KEY, collapsed ? '1' : '0')
  }

  function toggleNavigatorDetail(): void {
    navigatorDetailCollapsed.value = !navigatorDetailCollapsed.value
    localStorage.setItem(
      NAVIGATOR_DETAIL_COLLAPSED_KEY,
      navigatorDetailCollapsed.value ? '1' : '0'
    )
  }

  return {
    themeMode,
    alwaysOnTop,
    sessionTabLayout,
    sessionTabRailCollapsed,
    navigatorDetailCollapsed,
    applyRendererTheme,
    setAlwaysOnTop,
    toggleAlwaysOnTop,
    toggleTheme,
    setSessionTabLayout,
    setSessionTabRailCollapsed,
    toggleNavigatorDetail
  }
}
