export const NAVIGATOR_MIN_WIDTH = 400
export const NAVIGATOR_MAX_WIDTH = 760

export function defaultNavigatorWidth(width = window.innerWidth): number {
  if (width <= 1150) return 400
  if (width <= 1280) return 420
  if (width <= 1680) return 460
  return 500
}

export function readStoredNavigatorWidth(storageKey = 'odyterm.desktop-v2.navigator-width'): number {
  const stored = Number(localStorage.getItem(storageKey))
  return Number.isFinite(stored) && stored > 0 ? stored : defaultNavigatorWidth()
}
