export type HistoryState = {
  past: string[]
  present: string
  future: string[]
}

export function historyStart(present: string): HistoryState {
  return { past: [], present, future: [] }
}

export function historyPush(state: HistoryState, next: string, limit = 80): HistoryState {
  if (state.present === next) return state
  return { past: [...state.past, state.present].slice(-limit), present: next, future: [] }
}

export function historyUndo(state: HistoryState): HistoryState {
  const previous = state.past[state.past.length - 1]
  if (previous === undefined) return state
  return { past: state.past.slice(0, -1), present: previous, future: [state.present, ...state.future] }
}

export function historyRedo(state: HistoryState): HistoryState {
  const [next, ...rest] = state.future
  if (next === undefined) return state
  return { past: [...state.past, state.present], present: next, future: rest }
}
