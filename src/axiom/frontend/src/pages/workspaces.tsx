import { useEffect, useState, type FormEvent } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import type { Workspace } from "@/lib/types"

export function WorkspacesPage() {
  const { t } = useTranslation()
  const [rows, setRows] = useState<Workspace[] | null>(null)
  const [name, setName] = useState("")
  const [username, setUsername] = useState("")

  function load() {
    api.workspaces().then(setRows).catch(() => setRows([]))
  }

  useEffect(() => {
    load()
  }, [])

  async function create(event: FormEvent) {
    event.preventDefault()
    await api.createWorkspace(name)
    setName("")
    load()
  }

  async function add(workspaceId: number, event: FormEvent) {
    event.preventDefault()
    try {
      await api.addMember(workspaceId, username)
      setUsername("")
      load()
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : t("common.error"))
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-sm font-medium">{t("workspaces.title")}</h1>
      <form className="flex max-w-lg gap-2" onSubmit={create}>
        <Input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("projects.name")} required />
        <Button type="submit">{t("workspaces.create")}</Button>
      </form>
      {!rows ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : null}
      {rows && rows.length === 0 ? <p className="text-sm text-muted-foreground">{t("workspaces.empty")}</p> : null}
      <div className="grid gap-2">
        {(rows || []).map((workspace) => (
          <Card key={workspace.id}>
            <CardHeader><CardTitle>{workspace.name}</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="text-sm text-muted-foreground">{t("workspaces.members")}</div>
              <ul className="space-y-1 text-sm">
                {workspace.members.map((member) => (
                  <li key={member.user_id} className="flex justify-between">
                    <span>{member.display_name} · {member.username}</span>
                    <span className="text-muted-foreground">{member.role}</span>
                  </li>
                ))}
              </ul>
              <form className="flex gap-2" onSubmit={(event) => void add(workspace.id, event)}>
                <Input value={username} onChange={(event) => setUsername(event.target.value)} placeholder={t("workspaces.username")} />
                <Button type="submit" variant="outline">{t("workspaces.add")}</Button>
              </form>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
