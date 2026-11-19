import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { ApiError, api } from "@/lib/api"

type Outline = {
  sets: { name: string; elements: string[] }[]
  parameters: { name: string; index_sets: string[]; values: { index: string[]; value: number }[] }[]
  rhs: { name: string; sense: string; value: number }[]
}

export function ParameterGrid({ dsl, onCommit }: { dsl: string; onCommit: (aml: string) => void }) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const [data, setData] = useState<Outline | null>(null)
  const [error, setError] = useState("")
  const dataRef = useRef<Outline | null>(null)
  dataRef.current = data

  function replace(next: Outline) {
    dataRef.current = next
    setData(next)
  }

  useEffect(() => {
    let alive = true
    if (!dsl.trim()) {
      setData({ sets: [], parameters: [], rhs: [] })
      return
    }
    api.modelData(dsl).then((body) => {
      if (alive) {
        setData(body)
        setError("")
      }
    }).catch((reason: unknown) => {
      if (alive) setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error"))
    })
    return () => {
      alive = false
    }
  }, [dsl, zh, t])

  async function commit(next: Outline) {
    setData(next)
    try {
      const result = await api.applyModelData({ dsl, sets: next.sets, parameters: next.parameters, rhs: next.rhs })
      onCommit(result.aml)
    } catch (reason) {
      setError(reason instanceof ApiError ? (zh ? reason.message : reason.messageEn) : t("common.error"))
    }
  }

  if (!data) return <div className="app-skeleton m-3" data-grid="parameters" />
  const empty = data.sets.length === 0 && data.parameters.length === 0 && data.rhs.length === 0

  return (
    <div className="space-y-3 p-3 text-xs" data-grid="parameters">
      <p className="text-muted-foreground">{t("ux.gridLead")}</p>
      {error ? <p className="text-destructive">{error}</p> : null}
      {empty ? <p>{t("ux.gridEmpty")}</p> : null}
      {data.rhs.length ? (
        <table className="w-full border">
          <thead>
            <tr>
              <th className="border-b px-2 py-1 text-left">{t("ux.constraint")}</th>
              <th className="border-b px-2 py-1 text-left">{t("ux.sense")}</th>
              <th className="border-b px-2 py-1 text-left">{t("ux.value")}</th>
            </tr>
          </thead>
          <tbody>
            {data.rhs.map((row) => (
              <tr key={row.name}>
                <td className="border-b px-2 py-1 font-mono">{row.name}</td>
                <td className="border-b px-2 py-1">{row.sense}</td>
                <td className="border-b px-2 py-1">
                  <input
                    className="h-7 w-28 border px-1 font-mono"
                    data-rhs={row.name}
                    value={String(row.value)}
                    onChange={(event) => {
                      const value = Number(event.target.value)
                      if (!dataRef.current || !Number.isFinite(value)) return
                      replace({ ...dataRef.current, rhs: dataRef.current.rhs.map((item) => (item.name === row.name ? { ...item, value } : item)) })
                    }}
                    onBlur={() => dataRef.current && void commit(dataRef.current)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") (event.target as HTMLInputElement).blur()
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {data.sets.map((set) => (
        <label key={set.name} className="block">
          <span className="font-mono">{set.name}</span>
          <input
            className="mt-1 h-7 w-full border px-1 font-mono"
            data-set={set.name}
            value={set.elements.join(", ")}
            onChange={(event) => {
              if (!dataRef.current) return
              const elements = event.target.value.split(",").map((item) => item.trim()).filter(Boolean)
              replace({ ...dataRef.current, sets: dataRef.current.sets.map((item) => (item.name === set.name ? { ...item, elements } : item)) })
            }}
            onBlur={() => dataRef.current && void commit(dataRef.current)}
          />
        </label>
      ))}
      {data.parameters.map((param) => (
        <table key={param.name} className="w-full border">
          <thead>
            <tr>
              <th className="border-b px-2 py-1 text-left font-mono">{param.name}</th>
              <th className="border-b px-2 py-1 text-left">{t("ux.value")}</th>
            </tr>
          </thead>
          <tbody>
            {param.values.map((cell) => (
              <tr key={cell.index.join(",") || param.name}>
                <td className="border-b px-2 py-1 font-mono">{cell.index.join(", ") || param.name}</td>
                <td className="border-b px-2 py-1">
                  <input
                    className="h-7 w-28 border px-1 font-mono"
                    data-param={param.name}
                    value={String(cell.value)}
                    onChange={(event) => {
                      const value = Number(event.target.value)
                      if (!Number.isFinite(value)) return
                      if (!dataRef.current) return
                      const values = param.values.map((item) => (item.index.join(",") === cell.index.join(",") ? { ...item, value } : item))
                      replace({
                        ...dataRef.current,
                        parameters: dataRef.current.parameters.map((item) => (item.name === param.name ? { ...item, values } : item)),
                      })
                    }}
                    onBlur={() => dataRef.current && void commit(dataRef.current)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </div>
  )
}
