import { ref } from 'vue'

const CATALOG_WIDTH_KEY = 'device-tui.workflow-catalog-width'
const PROPERTIES_WIDTH_KEY = 'device-tui.workflow-properties-width-v2'

export function useWorkflowPanelLayout() {
  const workflowCatalogWidth = ref(224)
  const resizingWorkflowCatalog = ref(false)
  const workflowPropertiesWidth = ref(640)
  const resizingWorkflowProperties = ref(false)
  let catalogResizeStartX = 0
  let catalogResizeStartWidth = 224
  let propertiesResizeStartX = 0
  let propertiesResizeStartWidth = 640

  function catalogResizeLimit(): { min: number; max: number } {
    return {
      min: 180,
      max: Math.max(280, Math.min(480, Math.floor(window.innerWidth * 0.42)))
    }
  }

  function propertiesResizeLimit(): { min: number; max: number } {
    return { min: 380, max: Math.max(520, Math.min(760, Math.floor(window.innerWidth * 0.58))) }
  }

  function handleCatalogResize(event: PointerEvent): void {
    if (!resizingWorkflowCatalog.value) return
    const limits = catalogResizeLimit()
    workflowCatalogWidth.value = Math.min(
      limits.max,
      Math.max(limits.min, catalogResizeStartWidth + event.clientX - catalogResizeStartX)
    )
  }

  function finishCatalogResize(): void {
    if (!resizingWorkflowCatalog.value) return
    resizingWorkflowCatalog.value = false
    window.removeEventListener('pointermove', handleCatalogResize)
    try { window.localStorage.setItem(CATALOG_WIDTH_KEY, String(workflowCatalogWidth.value)) } catch { /* storage is optional */ }
  }

  function startWorkflowCatalogResize(event: PointerEvent): void {
    if (window.innerWidth <= 980) return
    event.preventDefault()
    event.stopPropagation()
    catalogResizeStartX = event.clientX
    catalogResizeStartWidth = workflowCatalogWidth.value
    resizingWorkflowCatalog.value = true
    window.addEventListener('pointermove', handleCatalogResize)
    window.addEventListener('pointerup', finishCatalogResize, { once: true })
  }

  function handlePropertiesResize(event: PointerEvent): void {
    if (!resizingWorkflowProperties.value) return
    const limits = propertiesResizeLimit()
    workflowPropertiesWidth.value = Math.min(
      limits.max,
      Math.max(limits.min, propertiesResizeStartWidth - event.clientX + propertiesResizeStartX)
    )
  }

  function finishPropertiesResize(): void {
    if (!resizingWorkflowProperties.value) return
    resizingWorkflowProperties.value = false
    window.removeEventListener('pointermove', handlePropertiesResize)
    try { window.localStorage.setItem(PROPERTIES_WIDTH_KEY, String(workflowPropertiesWidth.value)) } catch { /* storage is optional */ }
  }

  function startWorkflowPropertiesResize(event: PointerEvent): void {
    if (window.innerWidth <= 980) return
    event.preventDefault()
    event.stopPropagation()
    propertiesResizeStartX = event.clientX
    propertiesResizeStartWidth = workflowPropertiesWidth.value
    resizingWorkflowProperties.value = true
    window.addEventListener('pointermove', handlePropertiesResize)
    window.addEventListener('pointerup', finishPropertiesResize, { once: true })
  }

  function restoreWorkflowPanelWidths(): void {
    try {
      const saved = Number(window.localStorage.getItem(CATALOG_WIDTH_KEY) || 224)
      if (Number.isFinite(saved)) {
        const limits = catalogResizeLimit()
        workflowCatalogWidth.value = Math.min(limits.max, Math.max(limits.min, saved))
      }
    } catch { /* storage is optional */ }
    try {
      const saved = Number(window.localStorage.getItem(PROPERTIES_WIDTH_KEY) || 640)
      if (Number.isFinite(saved)) {
        const limits = propertiesResizeLimit()
        workflowPropertiesWidth.value = Math.min(limits.max, Math.max(limits.min, saved))
      }
    } catch { /* storage is optional */ }
  }

  function disposeWorkflowPanelLayout(): void {
    window.removeEventListener('pointermove', handleCatalogResize)
    window.removeEventListener('pointerup', finishCatalogResize)
    window.removeEventListener('pointermove', handlePropertiesResize)
    window.removeEventListener('pointerup', finishPropertiesResize)
  }

  return {
    workflowCatalogWidth,
    resizingWorkflowCatalog,
    workflowPropertiesWidth,
    resizingWorkflowProperties,
    startWorkflowCatalogResize,
    startWorkflowPropertiesResize,
    restoreWorkflowPanelWidths,
    disposeWorkflowPanelLayout
  }
}
