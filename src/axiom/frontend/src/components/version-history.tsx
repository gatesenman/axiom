import { useTranslation } from "react-i18next"
import { Button } from "@/components/ui/button"

export type VersionRow = {
  id: number
  label: string
  dsl: string
  statement: string
  created_at: string
}

export function VersionHistory({
  versions,
  onSave,
  onRollback,
}: {
  versions: VersionRow[]
  onSave: () => void
  onRollback: (version: VersionRow) => void
}) {
  const { t } = useTranslation()
  return (
    <div data-versions className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-sidebar-foreground/70">{t("ux.versions")}</span>
        <Button size="xs" variant="outline" onClick={onSave}>{t("ux.saveVersion")}</Button>
      </div>
      {versions.length === 0 ? <p className="text-sidebar-foreground/60">{t("ux.versionsEmpty")}</p> : null}
      {versions.slice(0, 8).map((version) => (
        <div key={version.id} className="flex items-center gap-1">
          <span className="min-w-0 flex-1 truncate" title={version.label}>{version.label}</span>
          <button type="button" className="text-primary" onClick={() => onRollback(version)}>{t("ux.rollback")}</button>
        </div>
      ))}
    </div>
  )
}
