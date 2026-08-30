export interface ContextMenuPoint {
  x: number
  y: number
}

const CONTEXT_MENU_EDGE_GAP = 8
const CONTEXT_MENU_FALLBACK_WIDTH = 210
const CONTEXT_MENU_FALLBACK_HEIGHT = 320
const CONTEXT_MENU_OPEN_EVENT = 'odyterm:context-menu-open'

export function announceContextMenuOpen(): void {
  window.dispatchEvent(new Event(CONTEXT_MENU_OPEN_EVENT))
}

export function subscribeContextMenuOpen(closeMenus: () => void): () => void {
  window.addEventListener(CONTEXT_MENU_OPEN_EVENT, closeMenus)
  return () => window.removeEventListener(CONTEXT_MENU_OPEN_EVENT, closeMenus)
}

export function clampContextMenuPoint(
  x: number,
  y: number,
  width = CONTEXT_MENU_FALLBACK_WIDTH,
  height = CONTEXT_MENU_FALLBACK_HEIGHT
): ContextMenuPoint {
  const maxX = Math.max(CONTEXT_MENU_EDGE_GAP, window.innerWidth - width - CONTEXT_MENU_EDGE_GAP)
  const maxY = Math.max(CONTEXT_MENU_EDGE_GAP, window.innerHeight - height - CONTEXT_MENU_EDGE_GAP)
  return {
    x: Math.min(Math.max(CONTEXT_MENU_EDGE_GAP, x), maxX),
    y: Math.min(Math.max(CONTEXT_MENU_EDGE_GAP, y), maxY)
  }
}

export function clampContextMenuElement(
  element: HTMLElement | null,
  x: number,
  y: number
): ContextMenuPoint {
  if (!element) return clampContextMenuPoint(x, y)
  const rect = element.getBoundingClientRect()
  return clampContextMenuPoint(x, y, rect.width, rect.height)
}

export function focusFirstContextMenuItem(element: HTMLElement | null): void {
  element?.querySelector<HTMLElement>('[role="menuitem"]:not(:disabled)')?.focus({ preventScroll: true })
}

export function contextMenuTrigger(event: Event): HTMLElement | null {
  if (event.currentTarget instanceof HTMLElement) return event.currentTarget
  return document.activeElement instanceof HTMLElement ? document.activeElement : null
}

export function restoreContextMenuFocus(element: HTMLElement | null): void {
  if (!element) return
  queueMicrotask(() => {
    if (element.isConnected) element.focus({ preventScroll: true })
  })
}

function enabledContextMenuItems(element: HTMLElement | null): HTMLElement[] {
  return [...(element?.querySelectorAll<HTMLElement>('[role="menuitem"]:not(:disabled)') || [])]
    .filter((item) => item.getClientRects().length > 0)
}

export function handleContextMenuKeydown(
  event: KeyboardEvent,
  element: HTMLElement | null,
  closeAndRestore: () => void
): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closeAndRestore()
    return
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  const items = enabledContextMenuItems(element)
  if (!items.length) return
  event.preventDefault()
  event.stopPropagation()
  const currentIndex = items.indexOf(document.activeElement as HTMLElement)
  const nextIndex = event.key === 'Home' ? 0
    : event.key === 'End' ? items.length - 1
      : event.key === 'ArrowDown' ? (currentIndex + 1 + items.length) % items.length
        : (currentIndex - 1 + items.length) % items.length
  items[nextIndex].focus({ preventScroll: true })
}
