import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api } from "@/lib/api"
import type { AuditRow } from "@/lib/types"

export function AuditPage() {
  const { t } = useTranslation()
  const [rows, setRows] = useState<AuditRow[] | null>(null)

  useEffect(() => {
    api.audit().then(setRows).catch(() => setRows([]))
  }, [])

  return (
    <div className="space-y-4">
      <h1 className="text-sm font-medium">{t("audit.title")}</h1>
      {!rows ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : null}
      {rows && rows.length === 0 ? (
        <p className="border px-2 py-3 text-sm text-muted-foreground">{t("audit.empty")}</p>
      ) : null}
      {rows && rows.length > 0 ? (
        <div className="border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("audit.when")}</TableHead>
                  <TableHead>{t("audit.who")}</TableHead>
                  <TableHead>{t("audit.action")}</TableHead>
                  <TableHead>{t("audit.detail")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="text-xs">{row.created_at.slice(0, 19).replace("T", " ")}</TableCell>
                    <TableCell>{row.username}</TableCell>
                    <TableCell className="font-mono text-xs">{row.action}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{row.detail}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
        </div>
      ) : null}
    </div>
  )
}
