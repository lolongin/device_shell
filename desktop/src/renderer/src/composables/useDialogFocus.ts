import { nextTick, onBeforeUnmount, onMounted, type Ref, watch } from 'vue'

const FOCUSABLE_SELECTOR = [
  '[data-dialog-initial-focus]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'a[href]',
  '[tabindex]:not([tabindex="-1"])'
].join(',')

type DialogFocusOptions = {
  open?: Ref<boolean>
  initialFocus?: string
  restoreFocus?: () => HTMLElement | null
}

function activeHTMLElement(): HTMLElement | null {
  return document.activeElement instanceof HTMLElement ? document.activeElement : null
}

function focusableElements(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter((element) => {
    if (element.hasAttribute('disabled') || element.getAttribute('aria-hidden') === 'true') return false
    const style = window.getComputedStyle(element)
    return style.display !== 'none' && style.visibility !== 'hidden'
  })
}

export function useDialogFocus(dialog: Ref<HTMLElement | null>, options: DialogFocusOptions = {}) {
  let restoreTarget = activeHTMLElement()
  let active = false

  function rememberTrigger(): void {
    const explicitTarget = options.restoreFocus?.()
    if (explicitTarget) {
      restoreTarget = explicitTarget
      return
    }
    const current = activeHTMLElement()
    if (current && !dialog.value?.contains(current)) restoreTarget = current
  }

  async function focusDialog(): Promise<void> {
    active = true
    await nextTick()
    const element = dialog.value
    if (!element) return
    const preferred = options.initialFocus
      ? element.querySelector<HTMLElement>(options.initialFocus)
      : element.querySelector<HTMLElement>('[data-dialog-initial-focus]')
    ;(preferred || focusableElements(element)[0] || element).focus({ preventScroll: true })
  }

  function restoreFocus(): void {
    if (!active) return
    active = false
    const target = restoreTarget
    void nextTick(() => {
      if (target?.isConnected) target.focus({ preventScroll: true })
    })
  }

  function handleDialogKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Tab' || !dialog.value) return
    const focusable = focusableElements(dialog.value)
    if (!focusable.length) {
      event.preventDefault()
      dialog.value.focus({ preventScroll: true })
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const current = activeHTMLElement()
    if (event.shiftKey && (current === first || current === dialog.value)) {
      event.preventDefault()
      last.focus({ preventScroll: true })
    } else if (!event.shiftKey && current === last) {
      event.preventDefault()
      first.focus({ preventScroll: true })
    } else if (!current || !dialog.value.contains(current)) {
      event.preventDefault()
      first.focus({ preventScroll: true })
    }
  }

  if (options.open) {
    watch(options.open, (open, wasOpen) => {
      if (open) {
        if (!wasOpen) rememberTrigger()
        void focusDialog()
      } else if (wasOpen) {
        restoreFocus()
      }
    })
    onMounted(() => {
      if (options.open?.value) void focusDialog()
    })
  } else {
    onMounted(() => {
      rememberTrigger()
      void focusDialog()
    })
  }

  onBeforeUnmount(restoreFocus)

  return { handleDialogKeydown }
}
