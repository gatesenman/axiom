import { useEffect, useState, type FormEvent } from "react"
import { useTranslation } from "react-i18next"
import { useTheme } from "next-themes"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ProviderManager } from "@/components/provider-manager"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { BenchmarkRow, SolverInfo, User } from "@/lib/types"

const COMPARE_CLASSES = ["lp", "milp", "qp", "socp", "nlp", "minlp", "cp", "sdp"]

function ComparisonTable({ rows }: { rows: BenchmarkRow[] }) {
  const solvers = [...new Set(rows.map((row) => row.solver))]
  const byKey = new Map(rows.map((row) => [`${row.solver}:${row.class}`, row]))
  return (
    <div className="overflow-x-auto">
      <Table data-solver-compare>
        <TableHeader>
          <TableRow>
            <TableHead>solver</TableHead>
            {COMPARE_CLASSES.map((kind) => <TableHead key={kind}>{kind}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {solvers.map((solver) => (
            <TableRow key={solver}>
              <TableCell className="font-medium">{solver}</TableCell>
              {COMPARE_CLASSES.map((kind) => {
                const row = byKey.get(`${solver}:${kind}`)
                if (!row) return <TableCell key={kind} className="text-xs text-muted-foreground">—</TableCell>
                const text = row.agree && row.objective != null ? row.objective.toPrecision(6) : row.status
                return <TableCell key={kind} className={row.agree ? "text-xs" : "text-xs text-muted-foreground"} title={`${row.status} ${row.runtime_sec.toFixed(3)}s`}>{text}</TableCell>
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export function SettingsPage() {
  const { t, i18n } = useTranslation()
  const { setTheme, theme } = useTheme()
  const { user, refresh } = useAuth()
  const [solvers, setSolvers] = useState<SolverInfo[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [username, setUsername] = useState("")
  const [display, setDisplay] = useState("")
  const [password, setPassword] = useState("")
  const [benchmark, setBenchmark] = useState<BenchmarkRow[] | null>(null)
  const [comparing, setComparing] = useState(false)

  useEffect(() => {
    api.solvers().then(setSolvers).catch(() => undefined)
    if (user?.role === "admin") api.users().then(setUsers).catch(() => undefined)
  }, [user?.role])

  async function createUser(event: FormEvent) {
    event.preventDefault()
    const created = await api.createUser({ username, password, display_name: display, role: "member" })
    setUsers((current) => [...current, created])
    setUsername("")
    setDisplay("")
    setPassword("")
  }

  async function changeLocale(locale: string) {
    await i18n.changeLanguage(locale)
    localStorage.setItem("axiom_locale", locale)
    const next = await api.updateMe({ locale })
    refresh(next)
  }

  async function changeTheme(next: "light" | "dark" | "system") {
    setTheme(next)
    if (!user) return
    const updated = await api.updateMe({ theme: next })
    refresh(updated)
  }

  return (
    <div className="space-y-2">
      <h1 className="border-b pb-1 text-sm font-medium">{t("settings.title")}</h1>
      <div className="grid gap-2 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>{t("settings.language")}</CardTitle></CardHeader>
          <CardContent className="flex gap-2 py-2">
            <Button size="sm" variant={i18n.language.startsWith("zh") ? "default" : "outline"} onClick={() => void changeLocale("zh-CN")}>简体中文</Button>
            <Button size="sm" variant={i18n.language === "en" ? "default" : "outline"} onClick={() => void changeLocale("en")}>English</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>{t("settings.theme")}</CardTitle></CardHeader>
          <CardContent className="flex gap-2 py-2">
            {(["light", "dark", "system"] as const).map((item) => (
              <Button key={item} size="sm" variant={theme === item ? "default" : "outline"} onClick={() => void changeTheme(item)}>{t(`settings.${item}`)}</Button>
            ))}
            <Button size="sm" variant="outline" onClick={() => {
              const next = localStorage.getItem("axiom_motion") === "reduce" ? "full" : "reduce"
              localStorage.setItem("axiom_motion", next)
              document.documentElement.classList.toggle("reduce-motion", next === "reduce")
            }}>{t("ide.motion")}</Button>
          </CardContent>
        </Card>
      </div>

      <ProviderManager />

      <Card data-solver-manager>
        <CardHeader>
          <CardTitle>{t("settings.solvers")}</CardTitle>
          <p className="text-xs text-muted-foreground">{t("settings.runtimeNote")}</p>
        </CardHeader>
        <CardContent className="overflow-x-auto px-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>name</TableHead>
                <TableHead>status</TableHead>
                <TableHead>{t("settings.classes")}</TableHead>
                <TableHead>version</TableHead>
                <TableHead>license</TableHead>
                <TableHead>{t("settings.docs")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {solvers.map((item) => (
                <TableRow key={item.name}>
                  <TableCell>
                    <div className="font-medium">{item.label}</div>
                    <div className="text-xs text-muted-foreground">{item.distribution === "bundled" ? t("settings.bundled") : t("settings.detected")}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={item.available ? "secondary" : "outline"}>{item.available ? t("settings.available") : t("settings.missing")}</Badge>
                  </TableCell>
                  <TableCell className="max-w-48 text-xs">{(item.classes || item.capabilities).join(" ")}</TableCell>
                  <TableCell className="text-xs">{item.version || "—"}</TableCell>
                  <TableCell className="text-xs">{item.license_state || item.license}</TableCell>
                  <TableCell className="text-xs">
                    {item.docs_url ? <a className="underline" href={item.docs_url} target="_blank" rel="noreferrer">{t("settings.docs")}</a> : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.compare")}</CardTitle>
          <p className="text-xs text-muted-foreground">{t("settings.compareHint")}</p>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button type="button" variant="outline" disabled={comparing} onClick={() => {
            setComparing(true)
            api.benchmark().then((payload) => setBenchmark(payload.rows)).catch((reason) => {
              toast.error(reason instanceof ApiError ? reason.message : t("common.error"))
            }).finally(() => setComparing(false))
          }}>{comparing ? t("settings.compareRunning") : t("settings.compareRun")}</Button>
          {benchmark ? <ComparisonTable rows={benchmark} /> : <p className="text-xs text-muted-foreground">{t("settings.compareEmpty")}</p>}
        </CardContent>
      </Card>

      {user?.role === "admin" ? (
        <Card>
          <CardHeader><CardTitle>{t("settings.users")}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <form className="grid gap-2 md:grid-cols-4" onSubmit={createUser}>
              <Input value={username} onChange={(event) => setUsername(event.target.value)} placeholder={t("login.username")} required />
              <Input value={display} onChange={(event) => setDisplay(event.target.value)} placeholder={t("settings.display")} />
              <Input value={password} onChange={(event) => setPassword(event.target.value)} placeholder={t("settings.password")} type="password" required />
              <Button type="submit">{t("settings.newUser")}</Button>
            </form>
            <ul className="space-y-1 text-sm">
              {users.map((item) => (
                <li key={item.id} className="flex justify-between border-b py-1">
                  <span>{item.display_name} · {item.username}</span>
                  <span className="text-muted-foreground">{item.role}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
