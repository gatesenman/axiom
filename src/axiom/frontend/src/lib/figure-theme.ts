/** Figure design tokens: screen dark, screen light, and a publication plate. */

export type FigureThemeName = "screen-dark" | "screen-light" | "publication"

export type FigurePalette = {
  name: FigureThemeName
  bg: string
  ink: string
  muted: string
  grid: string
  minor: string
  bar: string
  alt: string
  neg: string
  region: string
  line: string
  font: string
  axisSize: number
  titleSize: number
  captionSize: number
  categorical: string[]
  columnIn: { one: number; two: number }
  weights: { axis: number; grid: number; minor: number; data: number; emphasis: number }
}

export const OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"]
export const TABLEAU10 = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"]

const VIRIDIS = ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"]
const CIVIDIS = ["#00224e", "#123570", "#3b496c", "#575d6d", "#707173", "#8a8678", "#a59c74", "#c3b369", "#e1cc55", "#fee838"]
const BATLOW = ["#011959", "#1b3a72", "#3d5d86", "#628278", "#8aa07a", "#b8b56a", "#e0a14a", "#e06a32", "#c23b2e"]
const RDBU = ["#053061", "#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f7f7f7", "#fddbc7", "#f4a582", "#d6604d", "#b2182b", "#67001f"]

const SANS = 'Inter, "Source Sans 3", "Noto Sans SC", "Source Han Sans SC", "Segoe UI", sans-serif'
const SERIF = '"STIX Two Text", "Noto Serif SC", "Liberation Serif", Times, "Times New Roman", serif'

const publication: FigurePalette = {
  name: "publication",
  bg: "#ffffff",
  ink: "#111111",
  muted: "#4d463c",
  grid: "#d9d3c7",
  minor: "#eeeae3",
  bar: "#0072B2",
  alt: "#009E73",
  neg: "#D55E00",
  region: "#d6e4f0",
  line: "#4d463c",
  font: SERIF,
  axisSize: 11,
  titleSize: 15,
  captionSize: 12,
  categorical: OKABE_ITO,
  columnIn: { one: 3.5, two: 7.16 },
  weights: { axis: 0.8, grid: 0.5, minor: 0.35, data: 1.35, emphasis: 2 },
}

const screenLight: FigurePalette = {
  ...publication,
  name: "screen-light",
  bg: "#f7f6f3",
  ink: "#1a1c1e",
  muted: "#5c574e",
  grid: "#e4dfd6",
  minor: "#efece6",
  font: SANS,
  axisSize: 12,
  titleSize: 16,
  categorical: TABLEAU10,
}

const screenDark: FigurePalette = {
  ...publication,
  name: "screen-dark",
  bg: "#14161a",
  ink: "#e8e4da",
  muted: "#a39e92",
  grid: "rgba(232,228,218,0.14)",
  minor: "rgba(232,228,218,0.07)",
  bar: "#56B4E9",
  alt: "#009E73",
  neg: "#E69F00",
  region: "#1d3a52",
  line: "#c8c2b4",
  font: SANS,
  axisSize: 12,
  titleSize: 16,
  categorical: TABLEAU10,
}

export function themeFor(name: FigureThemeName): FigurePalette {
  if (name === "screen-dark") return screenDark
  if (name === "screen-light") return screenLight
  return publication
}

/** Publication palette. Existing charts import these field names. */
export const paper = {
  ink: publication.ink,
  muted: publication.muted,
  grid: publication.grid,
  bar: publication.bar,
  alt: publication.alt,
  neg: publication.neg,
  region: publication.region,
  line: publication.line,
}

export function readFigureTheme(): FigureThemeName {
  try {
    const stored = localStorage.getItem("axiom.figureTheme")
    if (stored === "publication" || stored === "screen-dark" || stored === "screen-light") return stored
    if (document.documentElement.classList.contains("dark")) return "screen-dark"
  } catch {
    /* node tests have no document */
  }
  return "screen-light"
}

export function setFigureTheme(name: FigureThemeName) {
  localStorage.setItem("axiom.figureTheme", name)
  window.dispatchEvent(new Event("axiom-figure-theme"))
}

export function sampleRamp(stops: string[], t: number): string {
  const clamped = Math.min(1, Math.max(0, t))
  if (stops.length === 1) return stops[0]
  const scaled = clamped * (stops.length - 1)
  const index = Math.min(stops.length - 2, Math.floor(scaled))
  const local = scaled - index
  return mixHex(stops[index], stops[index + 1], local)
}

export function colormap(name: "viridis" | "cividis" | "batlow", t: number): string {
  const stops = name === "cividis" ? CIVIDIS : name === "batlow" ? BATLOW : VIRIDIS
  return sampleRamp(stops, t)
}

export function divergingRdBu(t: number): string {
  const clamped = Math.min(1, Math.max(-1, t))
  return sampleRamp(RDBU, (clamped + 1) / 2)
}

export function formatSI(value: number, unit = ""): string {
  if (!Number.isFinite(value)) return "—"
  const sign = value < 0 ? "−" : ""
  const abs = Math.abs(value)
  const table: [number, string][] = [[1e12, "T"], [1e9, "G"], [1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"]]
  const [scale, prefix] = table.find(([step]) => abs >= step) || [1, ""]
  const scaled = abs / scale
  const digits = scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2
  const body = trimZeros(scaled.toFixed(digits))
  const unitText = `${prefix}${unit}`
  return unitText ? `${sign}${body}\u202f${unitText}` : `${sign}${body}`
}

export const MARKERS = ["circle", "square", "triangle", "diamond"] as const

function trimZeros(text: string) {
  return text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text
}

function mixHex(left: string, right: string, t: number) {
  const a = hex(left)
  const b = hex(right)
  const channels = a.map((channel, index) => Math.round(channel + (b[index] - channel) * t))
  return `rgb(${channels[0]} ${channels[1]} ${channels[2]})`
}

function hex(value: string) {
  const raw = value.replace("#", "")
  return [0, 2, 4].map((index) => Number.parseInt(raw.slice(index, index + 2), 16))
}
