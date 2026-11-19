export {}

declare global {
  interface Window {
    axiom?: {
      apiBase?: string
      getApiBase?: () => Promise<string>
      sidecarStatus?: () => Promise<{ state: string; base: string; detail: string; port: number; restarts: number }>
      restartSidecar?: () => Promise<{ state: string; base: string; detail: string; port: number; restarts: number }>
      onSidecar?: (callback: (status: { state: string; base: string; detail: string; port: number; restarts: number }) => void) => () => void
      openLogs?: () => Promise<string>
      window?: {
        minimize: () => void
        maximize: () => void
        close: () => void
      }
      notify?: (title: string, body: string) => Promise<boolean>
    }
  }
}
