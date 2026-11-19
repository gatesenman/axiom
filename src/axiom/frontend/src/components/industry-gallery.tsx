import { useTranslation } from "react-i18next"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import type { TemplateInfo } from "@/lib/types"

export const INDUSTRY_IDS = ["production-planning", "transportation", "staffing", "facility-location"]

export function IndustryGallery({
  open,
  templates,
  onOpenChange,
  onTry,
}: {
  open: boolean
  templates: TemplateInfo[]
  onOpenChange: (open: boolean) => void
  onTry: (item: TemplateInfo) => void
}) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const items = INDUSTRY_IDS.map((id) => templates.find((item) => item.id === id)).filter((item): item is TemplateInfo => Boolean(item))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("ux.gallery")}</DialogTitle>
        </DialogHeader>
        <div data-gallery className="space-y-2">
          <p className="text-xs text-muted-foreground">{t("ux.galleryLead")}</p>
          {items.map((item) => (
            <div key={item.id} className="flex items-center justify-between gap-2 border px-2 py-2">
              <div className="min-w-0">
                <div className="text-sm">{zh ? item.title_zh : item.title_en}</div>
                <div className="truncate text-xs text-muted-foreground">{zh ? item.summary_zh : item.summary_en}</div>
              </div>
              <Button size="sm" variant="outline" aria-label="Try industry template" onClick={() => { onOpenChange(false); onTry(item) }}>
                {t("ux.tryIndustry")}
              </Button>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
