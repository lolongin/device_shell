import { nextTick, watch, type Ref } from 'vue'
import { clampContextMenuElement, focusFirstContextMenuItem } from '../contextMenu'

type PositionedMenu = { x: number; y: number }

export function useContextMenuPlacement<T extends PositionedMenu>(menu: Ref<T | null>, element: Ref<HTMLElement | null>): void {
  watch(menu, async (current) => {
    if (!current) return
    await nextTick()
    if (menu.value !== current) return
    const point = clampContextMenuElement(element.value, current.x, current.y)
    if (point.x !== current.x || point.y !== current.y) menu.value = { ...current, ...point }
    focusFirstContextMenuItem(element.value)
  })
}
