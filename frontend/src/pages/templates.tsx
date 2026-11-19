import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import type { TemplateInfo } from "@/lib/types"

export function TemplatesPage() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [rows, setRows] = useState<TemplateInfo[] | null>(null)
  const [query, setQuery] = useState("")
  const zh = i18n.language.startsWith("zh")

  useEffect(() => {
    api.templates().then(setRows).catch(() => setRows([]))
  }, [])

  async function createFromTemplate(item: TemplateInfo) {
    const full = await api.template(item.id)
    const project = await api.createProject({
      title: zh ? full.title_zh : full.title_en,
      statement: zh ? full.summary_zh : full.summary_en,
      dsl: full.dsl || "",
      locale: zh ? "zh-CN" : "en",
    })
    navigate(`/projects/${project.id}`)
  }

  const visible = (rows || []).filter((item) => {
    const haystack = `${item.title_zh} ${item.title_en} ${item.category} ${item.kind}`.toLowerCase()
    return haystack.includes(query.trim().toLowerCase())
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{t("templates.title")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("templates.lead")}</p>
        </div>
        <Input className="max-w-xs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("common.search")} />
      </div>
      {!rows ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : null}
      {rows && visible.length === 0 ? <p className="text-sm text-muted-foreground">{t("templates.empty")}</p> : null}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {visible.map((item) => (
          <Card key={item.id}>
            <CardHeader>
              <CardTitle className="flex items-start justify-between gap-2">
                <span>{zh ? item.title_zh : item.title_en}</span>
                <Badge variant="outline">{item.kind}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">{zh ? item.summary_zh : item.summary_en}</p>
              <div className="text-xs text-muted-foreground">{item.category}</div>
              <Button size="sm" onClick={() => void createFromTemplate(item)}>{t("templates.use")}</Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
