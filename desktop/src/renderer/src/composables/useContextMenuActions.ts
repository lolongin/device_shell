import type { Ref } from 'vue'
import { announceContextMenuOpen, clampContextMenuPoint, contextMenuTrigger } from '../contextMenu'

export interface MenuPoint { x: number; y: number }

export function useContextMenuActions<T extends Record<string, unknown>>(menu: Ref<T | null>, returnFocus: Ref<HTMLElement | null>) {
  function open(event: MouseEvent, value: T): void {
    announceContextMenuOpen()
    returnFocus.value = contextMenuTrigger(event)
    menu.value = { ...value, ...clampContextMenuPoint(event.clientX, event.clientY) } as T
  }
  function openAt(event: KeyboardEvent, value: T, offset = 28): void {
    event.preventDefault()
    announceContextMenuOpen()
    const target = event.currentTarget as HTMLElement | null
    const rect = target?.getBoundingClientRect()
    returnFocus.value = target
    menu.value = { ...value, x: rect ? rect.left + offset : 128, y: rect ? rect.top + offset : 128 } as T
  }
  function close(): void { menu.value = null }
  function openFromKeyboard(event: KeyboardEvent, value: T, offset = 28): void {
    if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
    openAt(event, value, offset)
  }
  return { open, openAt, openFromKeyboard, close }
}
