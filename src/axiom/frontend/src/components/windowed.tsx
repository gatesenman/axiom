import { useState, type ReactNode } from "react"

/** Renders only the rows inside the viewport. Short lists should skip this. */
export function Windowed({
  count,
  rowHeight,
  height,
  children,
}: {
  count: number
  rowHeight: number
  height: number
  children: (index: number) => ReactNode
}) {
  const [scroll, setScroll] = useState(0)
  const start = Math.max(0, Math.floor(scroll / rowHeight) - 2)
  const visible = Math.ceil(height / rowHeight) + 5
  const end = Math.min(count, start + visible)
  const indexes: number[] = []
  for (let index = start; index < end; index += 1) indexes.push(index)
  return (
    <div className="overflow-auto" style={{ height }} onScroll={(event) => setScroll(event.currentTarget.scrollTop)}>
      <div style={{ height: count * rowHeight, position: "relative" }}>
        <div style={{ position: "absolute", top: start * rowHeight, left: 0, right: 0 }}>
          {indexes.map((index) => (
            <div key={index} style={{ height: rowHeight, overflow: "hidden" }}>
              {children(index)}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
