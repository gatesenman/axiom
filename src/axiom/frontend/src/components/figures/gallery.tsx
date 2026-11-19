import { useState, type ReactNode } from "react"
import { setFigureTheme, themeFor, type FigureThemeName } from "@/lib/figure-theme"
import { useFigurePalette } from "@/components/figures/theme"
import {
  CloudNote,
  Composer,
  ConvergencePlate,
  DistributionPlate,
  FeasiblePlate,
  GanttPlate,
  HeatPlate,
  Lollipop,
  MorrisPlate,
  N2Plate,
  NetworkPlate,
  ParallelPlate,
  ParetoPlate,
  ProfilePlate,
  SankeyPlate,
  SobolPlate,
  Sparkline,
  SurfacePlate,
  ViolinPlate,
  TornadoPlate,
  useGalleryRecords,
} from "@/components/figures/plates"

const THEMES: FigureThemeName[] = ["screen-dark", "screen-light", "publication"]

export function FigureGallery() {
  const palette = useFigurePalette()
  const [clustered, setClustered] = useState(false)
  const records = useGalleryRecords()
  const matrix = [
    [1, 0.4, -0.2],
    [0.4, 1, 0.6],
    [-0.2, 0.6, 1],
  ]
  return (
    <main className="min-h-screen overflow-auto p-4" style={{ background: palette.bg, color: palette.ink, fontFamily: palette.font }} data-figure-gallery>
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <h1 className="text-base font-medium">图形规范</h1>
        {THEMES.map((name) => (
          <button key={name} type="button" className="border px-2 py-1 text-xs" data-theme-choice={name} onClick={() => setFigureTheme(name)}>{themeFor(name).name}</button>
        ))}
        <button type="button" className="border px-2 py-1 text-xs" onClick={() => setClustered((value) => !value)}>{clustered ? "原序" : "聚类"}</button>
        <a className="text-xs underline" href="/">返回工作室</a>
      </header>
      <div className="grid gap-3 lg:grid-cols-2">
        <Plate title="收敛"><ConvergencePlate palette={palette} series={[{ name: "HiGHS", points: [{ t: 0, gap: 1, lo: 0.8, hi: 1.2 }, { t: 1, gap: 0.2, lo: 0.15, hi: 0.3 }, { t: 2, gap: 0.01, lo: 0.008, hi: 0.02 }] }, { name: "SCIP", points: [{ t: 0, gap: 1 }, { t: 1, gap: 0.4 }, { t: 2, gap: 0.03 }] }]} /></Plate>
        <Plate title="帕累托"><ParetoPlate palette={palette} xLabel="f1" yLabel="f2" points={[{ x: 1, y: 5 }, { x: 2, y: 3 }, { x: 3.2, y: 2.2 }, { x: 4, y: 1.4 }, { x: 3, y: 4 }]} /></Plate>
        <Plate title="平行坐标"><ParallelPlate palette={palette} /></Plate>
        <Plate title="龙卷风"><TornadoPlate palette={palette} /></Plate>
        <Plate title="Sobol"><SobolPlate palette={palette} /></Plate>
        <Plate title="Morris"><MorrisPlate palette={palette} /></Plate>
        <Plate title="响应面"><SurfacePlate palette={palette} zLabel="目标" /></Plate>
        <Plate title="可行域"><FeasiblePlate palette={palette} /></Plate>
        <Plate title="影子价格"><Lollipop palette={palette} unit="元" rows={[{ name: "工时", value: 12.5 }, { name: "原料", value: -3.2 }, { name: "需求", value: 1.1 }]} /></Plate>
        <Plate title="N2"><N2Plate palette={palette} /></Plate>
        <Plate title="甘特"><GanttPlate palette={palette} now={6} rows={[{ id: "A", start: 0, end: 4, lane: "机床1" }, { id: "B", start: 4, end: 9, lane: "机床1" }, { id: "C", start: 1, end: 6, lane: "机床2" }]} /></Plate>
        <Plate title="分布"><DistributionPlate palette={palette} unit="元" values={[10, 12, 11, 14, 13, 18, 12, 11, 15, 16, 12]} /></Plate>
        <Plate title="小提琴"><ViolinPlate palette={palette} unit="元" values={[10, 12, 11, 14, 13, 18, 12, 11, 15, 16, 12, 19, 11]} /></Plate>
        <Plate title="热图"><HeatPlate palette={palette} labels={["x", "y", "z"]} matrix={matrix} clustered={clustered} /></Plate>
        <Plate title="桑基"><SankeyPlate palette={palette} edges={[{ source: "工厂", target: "华东", value: 40 }, { source: "工厂", target: "华南", value: 25 }, { source: "港口", target: "华东", value: 10 }]} /></Plate>
        <Plate title="网络"><NetworkPlate palette={palette} geo nodes={[{ id: "上海", lat: 31.2, lon: 121.5 }, { id: "北京", lat: 39.9, lon: 116.4 }, { id: "广州", lat: 23.1, lon: 113.3 }]} edges={[{ source: "上海", target: "北京", value: 12 }, { source: "上海", target: "广州", value: 8 }, { source: "北京", target: "广州", value: 4 }]} /></Plate>
        <Plate title="性能剖面"><ProfilePlate palette={palette} records={records} /></Plate>
        <Plate title="生命周期"><Sparkline palette={palette} values={[1400, 1500, 1628, 1620, 1628.5]} /></Plate>
        <Plate title="抽稀"><CloudNote palette={palette} count={100000} /></Plate>
      </div>
      <section className="mt-4">
        <h2 className="mb-2 text-sm">拼图</h2>
        <Composer palette={palette} children={[
          { key: "a", node: <TornadoPlate palette={palette} /> },
          { key: "b", node: <ParetoPlate palette={palette} xLabel="f1" yLabel="f2" points={[{ x: 1, y: 4 }, { x: 2, y: 2 }, { x: 4, y: 1 }]} /> },
        ]} />
      </section>
    </main>
  )
}

function Plate({ title, children }: { title: string; children: ReactNode }) {
  return (
    <figure className="border p-2" data-gallery-plate={title}>
      <figcaption className="mb-1 text-xs">{title}</figcaption>
      {children}
    </figure>
  )
}
