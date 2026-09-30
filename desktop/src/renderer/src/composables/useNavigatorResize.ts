import { computed, type ComputedRef, type Ref } from 'vue'
import { defaultNavigatorWidth, NAVIGATOR_MAX_WIDTH, NAVIGATOR_MIN_WIDTH } from '../app/navigator-layout'

interface NavigatorContext {
  windowWidth: Ref<number>
  navigatorWidth: Ref<number>
  navigatorResizing: Ref<boolean>
  navigatorVisible: Ref<boolean>
  sessionTabRailCollapsed: Ref<boolean>
  showSessionSidebar: ComputedRef<boolean>
  closeMenus: () => void
  widthStorageKey?: string
  visibleStorageKey?: string
}

const ACTIVITY_RAIL_WIDTH = 52

export function useNavigatorResize(context: NavigatorContext) {
  const widthStorageKey = context.widthStorageKey || 'odyterm.desktop-v2.navigator-width'
  const visibleStorageKey = context.visibleStorageKey || 'odyterm.desktop-v2.navigator-visible'

  const navigatorMaxWidth = computed(() => {
    const centerMinimum = context.windowWidth.value <= 1150 ? 420 : context.windowWidth.value <= 1280 ? 440 : context.windowWidth.value <= 1680 ? 460 : 520
    const sideManagerReserve = context.showSessionSidebar.value ? (context.sessionTabRailCollapsed.value ? 42 : 260) : 0
    return Math.max(NAVIGATOR_MIN_WIDTH, Math.min(NAVIGATOR_MAX_WIDTH, context.windowWidth.value - ACTIVITY_RAIL_WIDTH - centerMinimum - sideManagerReserve))
  })

  const effectiveNavigatorWidth = computed(() => Math.max(NAVIGATOR_MIN_WIDTH, Math.min(navigatorMaxWidth.value, context.navigatorWidth.value)))

  function setNavigatorWidth(value: number, persist = true): void {
    context.navigatorWidth.value = Math.round(Math.max(NAVIGATOR_MIN_WIDTH, Math.min(navigatorMaxWidth.value, value)))
    if (persist) localStorage.setItem(widthStorageKey, String(context.navigatorWidth.value))
  }
  function resizeNavigatorFromPointer(event: PointerEvent): void { setNavigatorWidth(event.clientX - ACTIVITY_RAIL_WIDTH) }
  function stopNavigatorResize(): void {
    if (!context.navigatorResizing.value) return
    context.navigatorResizing.value = false
    window.removeEventListener('pointermove', resizeNavigatorFromPointer)
    window.removeEventListener('pointerup', stopNavigatorResize)
    window.removeEventListener('pointercancel', stopNavigatorResize)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  function startNavigatorResize(event: PointerEvent): void {
    event.preventDefault()
    context.navigatorResizing.value = true
    resizeNavigatorFromPointer(event)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', resizeNavigatorFromPointer)
    window.addEventListener('pointerup', stopNavigatorResize)
    window.addEventListener('pointercancel', stopNavigatorResize)
  }
  function handleNavigatorResizeKeydown(event: KeyboardEvent): void {
    if (event.key === 'Home') { event.preventDefault(); setNavigatorWidth(defaultNavigatorWidth(context.windowWidth.value)); return }
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const step = event.shiftKey ? 40 : 10
    setNavigatorWidth(effectiveNavigatorWidth.value + (event.key === 'ArrowRight' ? step : -step))
  }
  function resetNavigatorWidth(): void { setNavigatorWidth(defaultNavigatorWidth(context.windowWidth.value)) }
  function setNavigatorVisible(visible: boolean): void {
    context.navigatorVisible.value = visible
    localStorage.setItem(visibleStorageKey, visible ? '1' : '0')
    if (!visible) stopNavigatorResize()
  }
  function handleWindowResize(): void {
    context.windowWidth.value = window.innerWidth
    if (context.navigatorWidth.value > navigatorMaxWidth.value) setNavigatorWidth(navigatorMaxWidth.value)
    context.closeMenus()
  }
  return { navigatorMaxWidth, effectiveNavigatorWidth, setNavigatorWidth, resizeNavigatorFromPointer, stopNavigatorResize, startNavigatorResize, handleNavigatorResizeKeydown, resetNavigatorWidth, setNavigatorVisible, handleWindowResize }
}
