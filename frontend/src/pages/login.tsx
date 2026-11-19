import { useState, type FormEvent } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useSidecar } from "@/components/sidecar-banner"
import { loginToast, shortSidecarDetail } from "@/lib/login-error"
import { useAuth } from "@/lib/auth"

export function SignInForm({ onDone }: { onDone?: () => void }) {
  const { t, i18n } = useTranslation()
  const { login } = useAuth()
  const [username, setUsername] = useState("demo")
  const [password, setPassword] = useState("demo1234")
  const [pending, setPending] = useState(false)
  const sidecar = useSidecar()
  const sidecarDown = sidecar.state === "down" || sidecar.state === "restarting"

  async function submit(event: FormEvent) {
    event.preventDefault()
    setPending(true)
    try {
      const user = await login(username, password)
      if (user.locale) {
        await i18n.changeLanguage(user.locale)
        localStorage.setItem("axiom_locale", user.locale)
      }
      onDone?.()
    } catch (error) {
      const toastBody = loginToast(error, i18n.language.startsWith("zh"), t("login.failed"))
      toast.error(toastBody.text)
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      <div className="space-y-1">
        <Label htmlFor="username" className="text-xs">{t("login.username")}</Label>
        <Input id="username" className="h-8" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" autoFocus />
      </div>
      <div className="space-y-1">
        <Label htmlFor="password" className="text-xs">{t("login.password")}</Label>
        <Input id="password" className="h-8" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
      </div>
      {sidecarDown ? (
        <p role="alert" data-sidecar-login={sidecar.state} className="text-xs text-destructive">
          {sidecar.state === "restarting" ? t("login.restarting") : t("login.down")}
          {sidecar.detail ? ` ${shortSidecarDetail(sidecar.detail)}` : ""}
        </p>
      ) : null}
      <Button className="h-8 w-full" type="submit" disabled={pending}>
        {pending ? t("common.loading") : t("ide.signIn")}
      </Button>
      <p className="text-[11px] text-muted-foreground">{t("login.demo")}</p>
    </form>
  )
}
