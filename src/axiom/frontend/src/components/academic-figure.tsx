import { useRef, useState, type ReactNode } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { useFigurePalette } from "@/components/figures/theme"
import { copyText } from "@/lib/decision"
import { jpegToPdf, tableCsv, tableLatex, vectorPdfDocument } from "@/lib/figure-export"
import { epsFromSeries, matplotlibScript, tikzSnippet } from "@/lib/figure-geometry"
import { latexFigure } from "@/lib/figures"
import { setFigureTheme, type FigureThemeName } from "@/lib/figure-theme"

const PRINT = "#fbfaf7"

export function AcademicFigure({
  id,
  index,
  title,
  subtitle,
  caption,
  plotClass,
  rows,
  children,
}: {
  id: string
  index: number
  title: string
  subtitle?: string
  caption: string
  plotClass?: string
  rows?: Array<Record<string, string | number | null | undefined>>
  children: ReactNode
}) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const palette = useFigurePalette()
  const plotRef = useRef<HTMLDivElement>(null)
  const kicker = zh ? `图 ${index}` : `Fig. ${index}`
  const [heading, setHeading] = useState(title)
  const [note, setNote] = useState(caption)
  const [xLabel, setXLabel] = useState("")
  const [yLabel, setYLabel] = useState("")
  const [yMin, setYMin] = useState("")
  const [yMax, setYMax] = useState("")
  const [column, setColumn] = useState<"one" | "two">("two")
  const [inspector, setInspector] = useState(false)
  const [notes, setNotes] = useState<{ x: number; y: number; text: string }[]>([])
  const [zoom, setZoom] = useState(1)

  async function save(kind: "svg" | "png" | "pdf", dpi = 300) {
    const canvas = plotRef.current?.querySelector("canvas")
    const svg = plotRef.current?.querySelector("svg")
    if (!svg && canvas) {
      await saveCanvas(canvas, kind, id, dpi, palette.bg)
      return
    }
    if (!svg) return
    const width = svg.clientWidth || 640
    const height = svg.clientHeight || 320
    const clone = svg.cloneNode(true) as SVGSVGElement
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg")
    clone.setAttribute("width", String(width))
    clone.setAttribute("height", String(height))
    if (!clone.getAttribute("viewBox")) clone.setAttribute("viewBox", `0 0 ${width} ${height}`)
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style")
    style.textContent = `text { font-family: ${palette.font}; } .recharts-cartesian-grid line { stroke: ${palette.grid}; stroke-width: ${palette.weights.grid}; }`
    clone.insertBefore(style, clone.firstChild)
    const xml = new XMLSerializer().serializeToString(clone)
    if (kind === "svg") {
      download(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }), `fig-${id}.svg`)
      return
    }
    if (kind === "pdf") {
      const vector = svgToVectorPdf(clone)
      if (vector) {
        download(new Blob([Uint8Array.from(vector)], { type: "application/pdf" }), `fig-${id}.pdf`)
        return
      }
    }
    const url = URL.createObjectURL(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }))
    try {
      const image = await loadImage(url)
      const scale = dpi / 96
      const canvas = document.createElement("canvas")
      canvas.width = Math.max(1, Math.round(width * scale))
      canvas.height = Math.max(1, Math.round(height * scale))
      const context = canvas.getContext("2d")
      if (!context) return
      context.fillStyle = palette.bg
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.drawImage(image, 0, 0, canvas.width, canvas.height)
      if (kind === "pdf") {
        const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92))
        if (!blob) return
        const pdf = jpegToPdf(new Uint8Array(await blob.arrayBuffer()), canvas.width, canvas.height, dpi)
        download(new Blob([Uint8Array.from(pdf)], { type: "application/pdf" }), `fig-${id}.pdf`)
        return
      }
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"))
      if (blob) download(blob, `fig-${id}.png`)
    } finally {
      URL.revokeObjectURL(url)
    }
  }

  async function copyLatex() {
    await copyText(latexFigure(id, note))
    toast.success(t("figures.copied"))
  }

  function numericRows() {
    return (rows || []).map((row, index) => {
      const nums = Object.entries(row).filter((entry) => typeof entry[1] === "number")
      return { x: Number(nums[0]?.[1] ?? index), y: Number(nums[1]?.[1] ?? nums[0]?.[1] ?? 0) }
    })
  }

  async function copyImage() {
    const svg = plotRef.current?.querySelector("svg")
    if (!svg) return
    const blob = await svgToPng(svg, 2, palette.bg)
    if (!blob) return
    try {
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })])
      toast.success(t("figures.copied"))
    } catch {
      await copyText(latexFigure(id, note))
      toast.success(t("figures.copied"))
    }
  }

  return (
    <figure
      className="fig"
      data-figure={id}
      data-fig-theme={palette.name}
      style={{ background: palette.bg, color: palette.ink, fontFamily: palette.font, maxWidth: palette.name === "publication" ? `${palette.columnIn[column]}in` : undefined }}
    >
      <header className="fig-head">
        <div>
          <div className="fig-kicker">{kicker}</div>
          <h3 className="fig-title">{heading}</h3>
          {subtitle ? <p className="fig-sub">{subtitle}</p> : null}
        </div>
        <div className="fig-tools">
          {(["screen-dark", "screen-light", "publication"] as FigureThemeName[]).map((name) => (
            <button key={name} type="button" data-fig-theme-choice={name} onClick={() => setFigureTheme(name)}>{name === "publication" ? (zh ? "出版" : "Paper") : name === "screen-dark" ? (zh ? "屏暗" : "Dark") : (zh ? "屏亮" : "Light")}</button>
          ))}
          <button type="button" onClick={() => void save("png", 300)}>PNG</button>
          <button type="button" onClick={() => void save("png", 600)}>600</button>
          <button type="button" onClick={() => void save("svg")}>SVG</button>
          <button type="button" onClick={() => void save("pdf", 300)}>PDF</button>
          <button type="button" onClick={() => download(new Blob([epsFromSeries(heading, numericRows())], { type: "application/postscript" }), `fig-${id}.eps`)}>EPS</button>
          <button type="button" onClick={() => void copyText(tikzSnippet(heading, rows || [])).then(() => toast.success(t("figures.copied")))}>TikZ</button>
          <button type="button" onClick={() => download(new Blob([matplotlibScript(heading, rows || [])], { type: "text/x-python" }), `fig-${id}.py`)}>Py</button>
          <button type="button" onClick={() => void copyLatex()}>LaTeX</button>
          <button type="button" onClick={() => void copyImage()}>{zh ? "复制" : "Copy"}</button>
          <button type="button" onClick={() => { setZoom(1); setNotes([]) }}>{zh ? "还原" : "Reset"}</button>
          <button type="button" onClick={() => setInspector((value) => !value)}>{zh ? "检查" : "Inspect"}</button>
          <button type="button" onClick={() => setColumn((value) => (value === "one" ? "two" : "one"))}>{column === "one" ? "3.5in" : "7.16in"}</button>
          {rows?.length ? (
            <>
              <button type="button" onClick={() => download(new Blob([tableCsv(rows)], { type: "text/csv" }), `fig-${id}.csv`)}>CSV</button>
              <button type="button" onClick={() => void copyText(tableLatex(rows, caption)).then(() => toast.success(t("figures.copied")))}>LaTeX table</button>
            </>
          ) : null}
        </div>
      </header>
      {inspector ? (
        <form className="mt-2 grid gap-1 text-xs sm:grid-cols-2" onSubmit={(event) => event.preventDefault()}>
          <input className="border bg-transparent px-1" aria-label={zh ? "标题" : "Title"} value={heading} onChange={(event) => setHeading(event.target.value)} />
          <input className="border bg-transparent px-1" aria-label={zh ? "说明" : "Caption"} value={note} onChange={(event) => setNote(event.target.value)} />
          <input className="border bg-transparent px-1" aria-label={zh ? "横轴" : "X label"} value={xLabel} placeholder={zh ? "横轴" : "X label"} onChange={(event) => setXLabel(event.target.value)} />
          <input className="border bg-transparent px-1" aria-label={zh ? "纵轴" : "Y label"} value={yLabel} placeholder={zh ? "纵轴" : "Y label"} onChange={(event) => setYLabel(event.target.value)} />
          <input className="border bg-transparent px-1" aria-label={zh ? "纵轴下限" : "Y min"} value={yMin} placeholder={zh ? "纵轴下限" : "Y min"} onChange={(event) => setYMin(event.target.value)} />
          <input className="border bg-transparent px-1" aria-label={zh ? "纵轴上限" : "Y max"} value={yMax} placeholder={zh ? "纵轴上限" : "Y max"} onChange={(event) => setYMax(event.target.value)} />
        </form>
      ) : null}
      {(xLabel || yLabel || yMin || yMax) ? (
        <p className="fig-sub" data-ylim={`${yMin},${yMax}`}>{[xLabel && `x: ${xLabel}`, yLabel && `y: ${yLabel}`, (yMin || yMax) && `ylim [${yMin || "auto"}, ${yMax || "auto"}]`].filter(Boolean).join(" · ")}</p>
      ) : null}
      <div
        ref={plotRef}
        className={plotClass ? `fig-plot ${plotClass}` : "fig-plot"}
        data-chart={id}
        style={{ background: palette.bg, transform: `scale(${zoom})`, transformOrigin: "top left" }}
        onWheel={(event) => {
          if (!event.altKey) return
          event.preventDefault()
          setZoom((value) => Math.min(4, Math.max(1, value + (event.deltaY < 0 ? 0.1 : -0.1))))
        }}
        onDoubleClick={(event) => {
          const rect = event.currentTarget.getBoundingClientRect()
          const text = window.prompt(zh ? "注释" : "Note", "")
          if (!text) return
          setNotes((current) => [...current, { x: event.clientX - rect.left, y: event.clientY - rect.top, text }])
        }}
      >
        {children}
        {notes.map((item) => (
          <span key={`${item.x}-${item.y}`} className="pointer-events-none absolute text-[11px]" style={{ left: item.x, top: item.y, color: palette.neg }}>→ {item.text}</span>
        ))}
      </div>
      <figcaption className="fig-caption">{kicker}. {note}</figcaption>
    </figure>
  )
}

async function svgToPng(svg: SVGSVGElement, scale: number, background: string) {
  const width = svg.clientWidth || 640
  const height = svg.clientHeight || 320
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg")
  clone.setAttribute("width", String(width))
  clone.setAttribute("height", String(height))
  const xml = new XMLSerializer().serializeToString(clone)
  const url = URL.createObjectURL(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }))
  try {
    const image = await loadImage(url)
    const plate = document.createElement("canvas")
    plate.width = Math.max(1, Math.round(width * scale))
    plate.height = Math.max(1, Math.round(height * scale))
    const context = plate.getContext("2d")
    if (!context) return null
    context.fillStyle = background
    context.fillRect(0, 0, plate.width, plate.height)
    context.drawImage(image, 0, 0, plate.width, plate.height)
    return await new Promise<Blob | null>((resolve) => plate.toBlob(resolve, "image/png"))
  } finally {
    URL.revokeObjectURL(url)
  }
}

async function saveCanvas(canvas: HTMLCanvasElement, kind: "svg" | "png" | "pdf", id: string, dpi = 300, background = PRINT) {
  const scale = dpi / 96
  const width = Math.max(1, Math.round(canvas.width * scale))
  const height = Math.max(1, Math.round(canvas.height * scale))
  const plate = document.createElement("canvas")
  plate.width = width
  plate.height = height
  const context = plate.getContext("2d")
  if (!context) return
  context.fillStyle = background
  context.fillRect(0, 0, width, height)
  context.drawImage(canvas, 0, 0, width, height)
  if (kind === "pdf") {
    const blob = await new Promise<Blob | null>((resolve) => plate.toBlob(resolve, "image/jpeg", 0.92))
    if (!blob) return
    const pdf = jpegToPdf(new Uint8Array(await blob.arrayBuffer()), width, height, dpi)
    download(new Blob([Uint8Array.from(pdf)], { type: "application/pdf" }), `fig-${id}.pdf`)
    return
  }
  if (kind === "svg") {
    const href = plate.toDataURL("image/png")
    const xml = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><image href="${href}" width="${width}" height="${height}"/></svg>`
    download(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }), `fig-${id}.svg`)
    return
  }
  const blob = await new Promise<Blob | null>((resolve) => plate.toBlob(resolve, "image/png"))
  if (blob) download(blob, `fig-${id}.png`)
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

function svgToVectorPdf(svg: SVGSVGElement) {
  const texts = [...svg.querySelectorAll("text")].map((node) => node.textContent || "")
  if (texts.some((text) => [...text].some((char) => char.charCodeAt(0) > 255))) return null
  const view = (svg.getAttribute("viewBox") || "0 0 560 280").split(/[\s,]+/).map(Number)
  const vbW = view[2] || 560
  const vbH = view[3] || 280
  const pageW = 7.16 * 72
  const scale = pageW / vbW
  const pageH = vbH * scale
  const px = (value: number) => (value * scale).toFixed(2)
  const py = (value: number) => (pageH - value * scale).toFixed(2)
  const ops = ["0.6 w"]
  for (const node of svg.querySelectorAll("line, rect, circle, polyline, polygon, path, text")) {
    if (node.closest("defs")) continue
    const element = node as SVGElement
    const fill = paint(element.getAttribute("fill"))
    const stroke = paint(element.getAttribute("stroke")) || (element.tagName === "line" || element.tagName === "polyline" ? "0 0 0" : "")
    if (element.tagName === "line") {
      ops.push(`${stroke || "0 0 0"} RG`)
      ops.push(`${px(num(element, "x1"))} ${py(num(element, "y1"))} m ${px(num(element, "x2"))} ${py(num(element, "y2"))} l S`)
    } else if (element.tagName === "rect") {
      const x = num(element, "x")
      const y = num(element, "y")
      const w = num(element, "width")
      const h = num(element, "height")
      ops.push(`${px(x)} ${py(y + h)} ${px(w)} ${px(h)} re`)
      ops.push(fill && stroke ? `${fill} rg ${stroke} RG B` : fill ? `${fill} rg f` : `${stroke || "0 0 0"} RG S`)
    } else if (element.tagName === "circle") {
      const r = num(element, "r") * scale
      ops.push(`${px(num(element, "cx"))} ${py(num(element, "cy"))} ${r.toFixed(2)} 0 360 arc`)
      ops.push(fill ? `${fill} rg f` : `${stroke || "0 0 0"} RG S`)
    } else if (element.tagName === "polyline" || element.tagName === "polygon") {
      const pairs = (element.getAttribute("points") || "").trim().split(/\s+/).map((pair) => pair.split(",").map(Number))
      if (pairs.length < 2) continue
      const commands = pairs.map((pair, index) => `${px(pair[0] || 0)} ${py(pair[1] || 0)} ${index === 0 ? "m" : "l"}`)
      ops.push(commands.join(" "))
      ops.push(element.tagName === "polygon" && fill ? `${fill} rg f` : `${stroke || "0 0 0"} RG S`)
    } else if (element.tagName === "path") {
      const drawn = pathOps(element.getAttribute("d") || "", px, py)
      if (!drawn) continue
      ops.push(drawn)
      ops.push(fill ? `${fill} rg f` : `${stroke || "0 0 0"} RG S`)
    } else if (element.tagName === "text" && element.textContent) {
      const size = (Number(element.getAttribute("font-size")) || 11) * scale
      ops.push(`BT /F1 ${size.toFixed(2)} Tf ${stroke || fill || "0 0 0"} rg ${px(num(element, "x"))} ${py(num(element, "y"))} Td (${pdfEscape(element.textContent)}) Tj ET`)
    }
  }
  if (ops.length < 2) return null
  return vectorPdfDocument(`${ops.join("\n")}\n`, pageW, pageH)
}

function num(element: Element, name: string) {
  return Number(element.getAttribute(name) || 0)
}

function paint(value: string | null) {
  if (!value || value === "none" || value === "transparent") return ""
  const hex = value.trim()
  if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
    const channels = [0, 2, 4].map((index) => (Number.parseInt(hex.slice(1 + index, 3 + index), 16) / 255).toFixed(3))
    return channels.join(" ")
  }
  return ""
}

function pathOps(d: string, px: (value: number) => string, py: (value: number) => string) {
  const tokens = d.match(/[MLCZmlcz]|-?\d*\.?\d+(?:e[-+]?\d+)?/g)
  if (!tokens) return ""
  let index = 0
  let cx = 0
  let cy = 0
  const commands: string[] = []
  const take = () => {
    const value = Number(tokens[index] || 0)
    index += 1
    return value
  }
  while (index < tokens.length) {
    const op = tokens[index]
    if (!/[MLCZmlcz]/.test(op)) return ""
    index += 1
    if (op === "M" || op === "L" || op === "m" || op === "l") {
      const x = op === op.toLowerCase() ? cx + take() : take()
      const y = op === op.toLowerCase() ? cy + take() : take()
      cx = x
      cy = y
      commands.push(`${px(x)} ${py(y)} ${op.toLowerCase() === "m" ? "m" : "l"}`)
    } else if (op === "C" || op === "c") {
      const points = [0, 1, 2].map(() => {
        const x = op === "c" ? cx + take() : take()
        const y = op === "c" ? cy + take() : take()
        return [x, y] as const
      })
      cx = points[2][0]
      cy = points[2][1]
      commands.push(points.map((point) => `${px(point[0])} ${py(point[1])}`).join(" ") + " c")
    } else if (op === "Z" || op === "z") {
      commands.push("h")
    }
  }
  return commands.join(" ")
}

function pdfEscape(value: string) {
  return value.replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)")
}

function loadImage(url: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error("figure"))
    image.src = url
  })
}

export const paper = {
  ink: "#1c1c1c",
  muted: "#5e584f",
  grid: "#d9d3c7",
  bar: "#3d4f63",
  alt: "#6e6256",
  neg: "#7d4b45",
  region: "#d7e0da",
  line: "#5c5348",
}

export const paperTick = { fontSize: 12, fill: paper.ink, fontFamily: '"Liberation Serif", Georgia, "Noto Serif SC", serif' }
