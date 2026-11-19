import { Component, type ErrorInfo, type ReactNode } from "react"
import { Button } from "@/components/ui/button"

export function StartupErrorScreen({ message }: { message: string }) {
  return (
    <main data-startup-error className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#1e1e1e] px-8 text-[#f4f6fc]">
      <h1 className="text-lg font-semibold">界面没有启动</h1>
      <p className="max-w-xl text-center text-sm text-[#c5c8d4]">The studio interface did not start. Retry loads the page again. The log folder contains main.log.</p>
      <pre className="max-h-56 w-full max-w-2xl overflow-auto whitespace-pre-wrap rounded-md border border-white/10 bg-black/30 p-3 text-xs">{message}</pre>
      <div className="flex gap-2">
        <Button type="button" onClick={() => window.location.reload()}>重试 Retry</Button>
        <Button type="button" variant="outline" onClick={() => void window.axiom?.openLogs?.()}>打开日志文件夹</Button>
      </div>
    </main>
  )
}

type BoundaryState = { error: Error | null }

export class StartupErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error.stack || error.message, info.componentStack)
  }

  render() {
    if (this.state.error) return <StartupErrorScreen message={this.state.error.stack || this.state.error.message} />
    return this.props.children
  }
}
