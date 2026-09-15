import { ref, computed, Ref } from 'vue'

export interface UndoRedoOptions<T> {
  initialState: T
  maxHistory?: number
}

export interface UndoRedoState<T> {
  state: Ref<T>
  canUndo: Ref<boolean>
  canRedo: Ref<boolean>
  commit: (newState: T) => void
  undo: () => void
  redo: () => void
  reset: (newState: T) => void
  clear: () => void
}

/**
 * 撤销/重做功能
 * 使用深拷贝管理历史状态
 */
export function useUndoRedo<T>(options: UndoRedoOptions<T>): UndoRedoState<T> {
  const { initialState, maxHistory = 50 } = options

  const past = ref<T[]>([]) as Ref<T[]>
  const present = ref<T>(deepClone(initialState)) as Ref<T>
  const future = ref<T[]>([]) as Ref<T[]>

  const canUndo = computed(() => past.value.length > 0)
  const canRedo = computed(() => future.value.length > 0)

  /**
   * 深拷贝对象
   */
  function deepClone<T>(obj: T): T {
    if (obj === null || typeof obj !== 'object') return obj
    try {
      return JSON.parse(JSON.stringify(obj))
    } catch (error) {
      console.error('Deep clone failed:', error)
      return obj
    }
  }

  /**
   * 提交新状态到历史
   */
  function commit(newState: T) {
    // 保存当前状态到历史
    past.value.push(deepClone(present.value))

    // 限制历史记录数量
    if (past.value.length > maxHistory) {
      past.value.shift()
    }

    // 更新当前状态
    present.value = deepClone(newState)

    // 清空 redo 栈（一旦有新操作，之前的 redo 历史就无效了）
    future.value = []
  }

  /**
   * 撤销操作
   */
  function undo() {
    if (!canUndo.value) return

    // 保存当前状态到 future
    future.value.push(deepClone(present.value))

    // 从 past 中恢复状态
    const previousState = past.value.pop()
    if (previousState) {
      present.value = deepClone(previousState)
    }
  }

  /**
   * 重做操作
   */
  function redo() {
    if (!canRedo.value) return

    // 保存当前状态到 past
    past.value.push(deepClone(present.value))

    // 从 future 中恢复状态
    const nextState = future.value.pop()
    if (nextState) {
      present.value = deepClone(nextState)
    }
  }

  /**
   * 重置到新状态，清空历史
   */
  function reset(newState: T) {
    past.value = []
    present.value = deepClone(newState)
    future.value = []
  }

  /**
   * 清空历史记录
   */
  function clear() {
    past.value = []
    future.value = []
  }

  return {
    state: present,
    canUndo: computed(() => canUndo.value),
    canRedo: computed(() => canRedo.value),
    commit,
    undo,
    redo,
    reset,
    clear
  }
}

/**
 * 键盘快捷键支持
 */
export function useUndoRedoShortcuts(
  undo: () => void,
  redo: () => void
): () => void {
  function handleKeyDown(e: KeyboardEvent) {
    // Ctrl+Z 或 Cmd+Z（Mac）
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
      e.preventDefault()
      undo()
    }

    // Ctrl+Shift+Z 或 Cmd+Shift+Z（Mac）或 Ctrl+Y
    if (
      ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'z') ||
      (e.ctrlKey && e.key === 'y')
    ) {
      e.preventDefault()
      redo()
    }
  }

  // 注册事件监听
  window.addEventListener('keydown', handleKeyDown)

  // 返回清理函数
  return () => {
    window.removeEventListener('keydown', handleKeyDown)
  }
}
