import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ApiError, api } from "@/lib/api"
import type { LlmDirectory, ProviderCard, ProviderModel, ProviderTestResult, RoleAssignment } from "@/lib/types"

const ROLE_IDS = ["planner", "modeler", "solver-advisor", "reviewer", "reporter"] as const

const EMPTY_ROLES: Record<string, RoleAssignment> = Object.fromEntries(ROLE_IDS.map((role) => [role, { chain: [], compete: false }]))

function contextLabel(value: number) {
  if (!value) return "—"
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value % 1_000_000 ? 1 : 0)}M`
  if (value >= 1024) return `${Math.round(value / 1024)}K`
  return String(value)
}

function flatten(directory: LlmDirectory | null) {
  return directory?.groups.flatMap((group) => group.providers) ?? []
}

export function ProviderManager() {
  const { t, i18n } = useTranslation()
  const zh = i18n.language.startsWith("zh")
  const [directory, setDirectory] = useState<LlmDirectory | null>(null)
  const [selectedId, setSelectedId] = useState("deepseek")
  const [draft, setDraft] = useState<ProviderCard | null>(null)
  const [query, setQuery] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [awsSecret, setAwsSecret] = useState("")
  const [awsSession, setAwsSession] = useState("")
  const [roles, setRoles] = useState<Record<string, RoleAssignment>>(EMPTY_ROLES)
  const [probe, setProbe] = useState<ProviderTestResult | null>(null)
  const [busy, setBusy] = useState("")
  const [loadError, setLoadError] = useState("")
  const [customName, setCustomName] = useState("")
  const [customUrl, setCustomUrl] = useState("http://127.0.0.1:8080/v1")
  const [customProtocol, setCustomProtocol] = useState("openai")
  const [extraId, setExtraId] = useState("")
  const [extraContext, setExtraContext] = useState("8192")
  const [extraTools, setExtraTools] = useState(true)
  const [extraJson, setExtraJson] = useState(true)
  const [extraVision, setExtraVision] = useState(false)
  const [extraReasoning, setExtraReasoning] = useState(false)

  function adopt(next: LlmDirectory, prefer?: string) {
    setDirectory(next)
    setRoles(next.roles)
    const cards = flatten(next)
    const id = prefer && cards.some((item) => item.id === prefer) ? prefer : cards.some((item) => item.id === selectedId) ? selectedId : cards[0]?.id
    if (id) {
      setSelectedId(id)
      const card = cards.find((item) => item.id === id) || null
      setDraft(card)
    }
  }

  useEffect(() => {
    api.llmDirectory().then((next) => adopt(next, "deepseek")).catch((reason) => {
      setLoadError(reason instanceof ApiError ? reason.message : t("settings.providers.loadError"))
    })
    // The directory is loaded once; later refreshes go through adopt().
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const cards = flatten(directory)
  const selected = cards.find((item) => item.id === selectedId) || null
  const view = draft && draft.id === selectedId ? draft : selected
  const modelSpec = view?.models.find((item) => item.id === view.model) || view?.models[0]

  const filteredGroups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (directory?.groups ?? []).map((group) => ({
      ...group,
      providers: group.providers.filter((item) => {
        if (!needle) return true
        return [item.id, item.name, item.name_zh, item.protocol].join(" ").toLowerCase().includes(needle)
      }),
    })).filter((group) => group.providers.length)
  }, [directory, query])

  function patch(partial: Partial<ProviderCard>) {
    setDraft((current) => current ? { ...current, ...partial } : current)
  }

  async function persist(partial: Partial<ProviderCard> & { extra_models?: ProviderModel[] }, toastOk = true) {
    if (!view) return null
    setBusy("save")
    try {
      await api.saveProvider(view.id, partial)
      const next = await api.llmDirectory()
      adopt(next, view.id)
      if (toastOk) toast.success(t("settings.saved"))
      return next
    } catch (reason) {
      toast.error(reason instanceof ApiError ? reason.message : t("common.error"))
      return null
    } finally {
      setBusy("")
    }
  }

  async function saveConfig() {
    if (!view) return
    await persist({
      enabled: view.enabled,
      base_url: view.base_url,
      model: view.model,
      proxy: view.proxy,
      timeout: Number(view.timeout) || 60,
      api_version: view.api_version,
      region: view.region,
      api_style: view.api_style,
      bedrock_mode: view.bedrock_mode,
      extra_models: view.models.filter((item) => item.custom),
    })
  }

  async function saveKey() {
    if (!view) return
    if (!apiKey && !awsSecret) return
    setBusy("key")
    try {
      await api.saveProviderKey(view.id, { api_key: apiKey, aws_secret: awsSecret, aws_session: awsSession })
      setApiKey("")
      setAwsSecret("")
      setAwsSession("")
      adopt(await api.llmDirectory(), view.id)
      toast.success(t("settings.saved"))
    } catch (reason) {
      toast.error(reason instanceof ApiError ? reason.message : t("common.error"))
    } finally {
      setBusy("")
    }
  }

  async function clearKey() {
    if (!view) return
    setBusy("key")
    try {
      await api.deleteProviderKey(view.id)
      adopt(await api.llmDirectory(), view.id)
      toast.success(t("settings.saved"))
    } catch (reason) {
      toast.error(reason instanceof ApiError ? reason.message : t("common.error"))
    } finally {
      setBusy("")
    }
  }

  async function toggle(item: ProviderCard, enabled: boolean) {
    setBusy("toggle")
    try {
      await api.saveProvider(item.id, { enabled })
      adopt(await api.llmDirectory(), item.id)
    } catch (reason) {
      toast.error(reason instanceof ApiError ? reason.message : t("common.error"))
    } finally {
      setBusy("")
    }
  }

  async function runTest() {
    if (!view) return
    setBusy("test")
    setProbe(null)
    try {
      const result = await api.testProvider(view.id)
      setProbe(result)
      toast[result.ok ? "success" : "error"](zh ? result.message : result.message_en)
      adopt(await api.llmDirectory(), view.id)
    } catch (reason) {
      const message = reason instanceof ApiError ? reason.message : t("common.error")
      setProbe({ ok: false, provider: view.id, latency_ms: 0, message, message_en: message })
      toast.error(message)
    } finally {
      setBusy("")
    }
  }

  async function fetchModels() {
    if (!view) return
    setBusy("models")
    try {
      const result = await api.fetchProviderModels(view.id)
      adopt(await api.llmDirectory(), view.id)
      toast.success(`${result.models.length}`)
    } catch (reason) {
      toast.error(reason instanceof ApiError ? reason.message : t("common.error"))
    } finally {
      setBusy("")
    }
  }

  async function addExtraModel() {
    if (!view || !extraId.trim()) return
    const extra: ProviderModel = {
      id: extraId.trim(),
      label: extraId.trim(),
      context: Number(extraContext) || 8192,
      tools: extraTools,
      json_mode: extraJson,
      vision: extraVision,
      reasoning: extraReasoning,
      input_usd_per_mtok: 0,
      output_usd_per_mtok: 0,
      custom: true,
    }
    const extras = [...view.models.filter((item) => item.custom).filter((item) => item.id !== extra.id), extra]
    setExtraId("")
    await persist({ extra_models: extras, model: extra.id }, true)
  }

  async function saveRoleAssignment() {
    setBusy("roles")
    try {
      const saved = await api.saveLlmRoles(roles)
      setRoles(saved.roles)
      adopt(await api.llmDirectory(), selectedId)
      window.dispatchEvent(new Event("axiom-settings"))
      toast.success(t("settings.saved"))
    } catch (reason) {
      toast.error(reason instanceof ApiError ? reason.message : t("common.error"))
    } finally {
      setBusy("")
    }
  }

  async function createCustom() {
    if (!customName.trim()) return
    setBusy("custom")
    try {
      const created = await api.addCustomProvider({ name: customName.trim(), base_url: customUrl, protocol: customProtocol, group: "local" })
      setCustomName("")
      adopt(await api.llmDirectory(), created.id)
      toast.success(t("settings.saved"))
    } catch (reason) {
      toast.error(reason instanceof ApiError ? reason.message : t("common.error"))
    } finally {
      setBusy("")
    }
  }

  function setHop(role: string, index: number, value: string) {
    const [provider, model] = value.split("::")
    setRoles((current) => {
      const chain = [...(current[role]?.chain ?? [])]
      chain[index] = { provider, model }
      return { ...current, [role]: { chain, compete: current[role]?.compete ?? false } }
    })
  }

  const enabledModels = cards.filter((item) => item.enabled).flatMap((item) => {
    const models = item.models.length ? item.models : [{ id: item.model || "model", label: item.model || "model", context: 0, tools: false, json_mode: false, vision: false, reasoning: false, input_usd_per_mtok: 0, output_usd_per_mtok: 0 }]
    return models.map((model) => ({ value: `${item.id}::${model.id}`, label: `${zh ? item.name_zh : item.name} · ${model.label}` }))
  })

  if (loadError) return <p className="text-sm text-destructive">{loadError}</p>
  if (!directory || !view) return <p className="text-sm text-muted-foreground">{t("settings.providers.loading")}</p>

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.llm")}</CardTitle>
          <p className="text-xs text-muted-foreground">{t("settings.providers.lead")}</p>
        </CardHeader>
        <CardContent className="grid gap-3 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="space-y-2" data-provider-list>
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("settings.providers.search")} />
            <div className="max-h-80 space-y-3 overflow-auto pr-1 lg:max-h-[32rem]">
              {filteredGroups.map((group) => (
                <div key={group.id}>
                  <div className="px-1 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground">{t(`settings.providers.${group.id}`)}</div>
                  <div className="space-y-1">
                    {group.providers.map((item) => (
                      <div
                        key={item.id}
                        data-provider-id={item.id}
                        className={`flex w-full items-center gap-2 rounded-md border px-2 py-1.5 ${item.id === selectedId ? "border-primary bg-muted/60" : "border-transparent hover:bg-muted/40"}`}
                      >
                        <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => { setSelectedId(item.id); setDraft(item); setProbe(null) }}>
                          <span className="grid size-7 shrink-0 place-items-center rounded-md text-[10px] font-semibold text-white" style={{ background: item.color }}>{item.monogram}</span>
                          <span className="min-w-0">
                            <span className="block truncate text-xs font-medium">{zh ? item.name_zh : item.name}</span>
                            <span className="block truncate text-[10px] text-muted-foreground">{item.protocol}</span>
                          </span>
                        </button>
                        <Switch
                          checked={item.enabled}
                          aria-label={`${zh ? item.name_zh : item.name} ${t("settings.providers.enabled")}`}
                          onCheckedChange={(checked) => void toggle(item, checked)}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="space-y-2 border-t pt-2">
              <div className="text-[11px] font-medium text-muted-foreground">{t("settings.providers.addProvider")}</div>
              <Input value={customName} onChange={(event) => setCustomName(event.target.value)} placeholder={t("settings.providers.name")} />
              <Input value={customUrl} onChange={(event) => setCustomUrl(event.target.value)} placeholder={t("settings.providers.base")} />
              <Select value={customProtocol} onValueChange={setCustomProtocol}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["openai", "anthropic", "gemini", "cohere", "bedrock"].map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
                </SelectContent>
              </Select>
              <Button size="sm" variant="outline" disabled={busy === "custom"} onClick={() => void createCustom()}>{t("settings.providers.addProvider")}</Button>
            </div>
          </div>

          <div className="space-y-3" data-provider-config>
            <div className="flex items-start gap-3">
              <span className="grid size-9 place-items-center rounded-md text-xs font-semibold text-white" style={{ background: view.color }}>{view.monogram}</span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{zh ? view.name_zh : view.name}</div>
                <p className="text-xs text-muted-foreground">{zh ? view.notes_zh : view.notes}</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-1" data-provider-caps>
              <Badge variant="outline">{view.protocol}</Badge>
              {modelSpec?.tools ? <Badge variant="outline">{t("settings.providers.tools")}</Badge> : null}
              {modelSpec?.json_mode ? <Badge variant="outline">{t("settings.providers.json")}</Badge> : null}
              {modelSpec?.vision ? <Badge variant="outline">{t("settings.providers.vision")}</Badge> : null}
              {modelSpec?.reasoning ? <Badge variant="outline">{t("settings.providers.reasoning")}</Badge> : null}
              <Badge variant="outline">{t("settings.providers.context")} {contextLabel(modelSpec?.context || 0)}</Badge>
              {view.key_set ? <Badge variant="secondary">{view.key_mask || "••••"}</Badge> : null}
            </div>

            {view.id === "mock" ? <p className="text-xs text-muted-foreground">{t("settings.providers.offline")}</p> : (
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5 md:col-span-2">
                  <Label>{t("settings.providers.base")}</Label>
                  <Input value={view.base_url} onChange={(event) => patch({ base_url: event.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label>{t("settings.providers.model")}</Label>
                  <Input value={view.model} onChange={(event) => patch({ model: event.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label>{t("settings.model")}</Label>
                  <Select value={view.models.some((item) => item.id === view.model) ? view.model : undefined} onValueChange={(value) => patch({ model: value })}>
                    <SelectTrigger><SelectValue placeholder={view.model} /></SelectTrigger>
                    <SelectContent>
                      {view.models.map((item) => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                {view.id === "openai" ? (
                  <div className="space-y-1.5">
                    <Label>{t("settings.providers.style")}</Label>
                    <Select value={view.api_style || "chat"} onValueChange={(value) => patch({ api_style: value })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="chat">{t("settings.providers.styleChat")}</SelectItem>
                        <SelectItem value="responses">{t("settings.providers.styleResponses")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                ) : null}
                {view.id === "azure" || view.auth === "azure" ? (
                  <div className="space-y-1.5">
                    <Label>{t("settings.providers.apiVersion")}</Label>
                    <Input value={view.api_version} onChange={(event) => patch({ api_version: event.target.value })} />
                  </div>
                ) : null}
                {view.protocol === "bedrock" ? (
                  <>
                    <div className="space-y-1.5">
                      <Label>{t("settings.providers.protocol")}</Label>
                      <Select value={view.bedrock_mode || "native"} onValueChange={(value) => patch({ bedrock_mode: value })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="native">{t("settings.providers.bedrockNative")}</SelectItem>
                          <SelectItem value="gateway">{t("settings.providers.bedrockGateway")}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label>{t("settings.providers.region")}</Label>
                      <Input value={view.region} onChange={(event) => patch({ region: event.target.value })} />
                    </div>
                  </>
                ) : null}
                <div className="space-y-1.5">
                  <Label>{view.protocol === "bedrock" && view.bedrock_mode !== "gateway" ? t("settings.providers.accessKey") : t("settings.key")}</Label>
                  <Input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" placeholder={view.key_mask || ""} autoComplete="off" />
                </div>
                {view.protocol === "bedrock" && view.bedrock_mode !== "gateway" ? (
                  <>
                    <div className="space-y-1.5">
                      <Label>{t("settings.providers.secret")}</Label>
                      <Input value={awsSecret} onChange={(event) => setAwsSecret(event.target.value)} type="password" placeholder={view.secret_set ? "••••" : ""} autoComplete="off" />
                    </div>
                    <div className="space-y-1.5 md:col-span-2">
                      <Label>{t("settings.providers.session")}</Label>
                      <Input value={awsSession} onChange={(event) => setAwsSession(event.target.value)} type="password" autoComplete="off" />
                    </div>
                  </>
                ) : null}
                <div className="space-y-1.5">
                  <Label>{t("settings.providers.proxy")}</Label>
                  <Input value={view.proxy} onChange={(event) => patch({ proxy: event.target.value })} placeholder="socks5://127.0.0.1:1080" />
                  <p className="text-[11px] text-muted-foreground">{t("settings.providers.proxyHint")}</p>
                </div>
                <div className="space-y-1.5">
                  <Label>{t("settings.providers.timeout")}</Label>
                  <Input value={String(view.timeout || 60)} onChange={(event) => patch({ timeout: Number(event.target.value) || 60 })} />
                </div>
                <div className="space-y-1.5 md:col-span-2">
                  <Label>{t("settings.providers.addModel")}</Label>
                  <div className="flex flex-wrap items-center gap-2">
                    <Input className="w-40" value={extraId} onChange={(event) => setExtraId(event.target.value)} placeholder={t("settings.providers.modelId")} />
                    <Input className="w-24" value={extraContext} onChange={(event) => setExtraContext(event.target.value)} placeholder={t("settings.providers.context")} />
                    <label className="flex items-center gap-1 text-[11px]"><input type="checkbox" checked={extraTools} onChange={(event) => setExtraTools(event.target.checked)} />{t("settings.providers.tools")}</label>
                    <label className="flex items-center gap-1 text-[11px]"><input type="checkbox" checked={extraJson} onChange={(event) => setExtraJson(event.target.checked)} />{t("settings.providers.json")}</label>
                    <label className="flex items-center gap-1 text-[11px]"><input type="checkbox" checked={extraVision} onChange={(event) => setExtraVision(event.target.checked)} />{t("settings.providers.vision")}</label>
                    <label className="flex items-center gap-1 text-[11px]"><input type="checkbox" checked={extraReasoning} onChange={(event) => setExtraReasoning(event.target.checked)} />{t("settings.providers.reasoning")}</label>
                    <Button size="sm" variant="outline" onClick={() => void addExtraModel()}>{t("settings.providers.addModel")}</Button>
                  </div>
                  {view.key_optional ? <p className="text-[11px] text-muted-foreground">{t("settings.providers.keyOptional")}</p> : <p className="text-[11px] text-muted-foreground">{t("settings.keyHint")}</p>}
                </div>
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              {view.id !== "mock" ? <Button size="sm" disabled={busy === "save"} onClick={() => void saveConfig()}>{t("settings.save")}</Button> : null}
              {view.id !== "mock" ? <Button size="sm" variant="outline" disabled={busy === "key"} onClick={() => void saveKey()}>{t("settings.providers.saveKey")}</Button> : null}
              {view.key_set ? <Button size="sm" variant="outline" onClick={() => void clearKey()}>{t("settings.providers.clearKey")}</Button> : null}
              {view.listable && view.id !== "mock" ? <Button size="sm" variant="outline" disabled={busy === "models"} onClick={() => void fetchModels()}>{busy === "models" ? t("settings.providers.fetching") : t("settings.providers.fetch")}</Button> : null}
              <Button size="sm" variant="outline" disabled={busy === "test"} onClick={() => void runTest()}>{t("settings.test")}</Button>
              {!view.builtin ? <Button size="sm" variant="outline" onClick={() => void api.deleteCustomProvider(view.id).then(() => api.llmDirectory().then((next) => adopt(next)))}>{t("settings.providers.remove")}</Button> : null}
            </div>
            {probe && probe.provider === view.id ? (
              <div data-test-result className={`rounded-md border px-3 py-2 text-xs ${probe.ok ? "border-emerald-700/40 text-emerald-700 dark:text-emerald-400" : "border-destructive/40 text-destructive"}`}>
                <div className="font-medium">{probe.ok ? t("settings.providers.testOk") : t("settings.providers.testFail")} · {t("settings.providers.latency")} {probe.latency_ms} ms</div>
                <div className="mt-1 whitespace-pre-wrap">{zh ? probe.message : probe.message_en}</div>
              </div>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card data-agent-models>
        <CardHeader>
          <CardTitle>{t("settings.providers.roles")}</CardTitle>
          <p className="text-xs text-muted-foreground">{t("settings.providers.rolesLead")}</p>
        </CardHeader>
        <CardContent className="space-y-3">
          {ROLE_IDS.map((role) => {
            const assignment = roles[role] || { chain: [], compete: false }
            const chain = assignment.chain.length ? assignment.chain : [{ provider: "", model: "" }]
            return (
              <div key={role} className="grid gap-2 border-b pb-2 md:grid-cols-[8rem_minmax(0,1fr)_auto]">
                <div className="text-xs font-medium">{t(`settings.providers.${role}`)}</div>
                <div className="space-y-1">
                  {chain.map((hop, index) => (
                    <Select key={`${role}-${index}`} value={hop.provider ? `${hop.provider}::${hop.model}` : undefined} onValueChange={(value) => setHop(role, index, value)}>
                      <SelectTrigger><SelectValue placeholder={index === 0 ? t("settings.providers.model") : t("settings.providers.fallback")} /></SelectTrigger>
                      <SelectContent>
                        {enabledModels.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  ))}
                </div>
                <div className="flex items-center gap-3">
                  <Button size="sm" variant="outline" disabled={chain.length >= 3} onClick={() => setRoles((current) => ({ ...current, [role]: { ...assignment, chain: [...chain, { provider: "", model: "" }] } }))}>{t("settings.providers.addFallback")}</Button>
                  <label className="flex items-center gap-2 text-xs">
                    <Switch checked={assignment.compete} onCheckedChange={(checked) => setRoles((current) => ({ ...current, [role]: { chain: (current[role]?.chain ?? []).filter((hop) => hop.provider), compete: checked } }))} />
                    {t("settings.providers.compete")}
                  </label>
                </div>
              </div>
            )
          })}
          <Button size="sm" disabled={busy === "roles"} onClick={() => void saveRoleAssignment()}>{t("settings.providers.saveRoles")}</Button>
        </CardContent>
      </Card>

      <Card data-provider-usage>
        <CardHeader>
          <CardTitle>{t("settings.providers.usage")}</CardTitle>
          <p className="text-xs text-muted-foreground">{t("settings.providers.priceNote")}</p>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex flex-wrap gap-3 text-xs">
            <span>{t("settings.providers.calls")} {directory.usage.totals.calls}</span>
            <span>{t("settings.providers.tokens")} {directory.usage.totals.prompt_tokens + directory.usage.totals.completion_tokens}</span>
            <span>{t("settings.providers.cost")} ${directory.usage.totals.cost_usd.toFixed(4)}</span>
          </div>
          {directory.usage.rows.length ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("settings.role")}</TableHead>
                    <TableHead>{t("settings.provider")}</TableHead>
                    <TableHead>{t("settings.model")}</TableHead>
                    <TableHead>{t("settings.providers.tokens")}</TableHead>
                    <TableHead>{t("settings.providers.cost")}</TableHead>
                    <TableHead>{t("settings.providers.latency")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...directory.usage.rows].reverse().slice(0, 12).map((row, index) => (
                    <TableRow key={`${row.at}-${index}`}>
                      <TableCell className="text-xs">{row.role}</TableCell>
                      <TableCell className="text-xs">{row.provider}</TableCell>
                      <TableCell className="text-xs">{row.model}</TableCell>
                      <TableCell className="text-xs">{row.prompt_tokens + row.completion_tokens}</TableCell>
                      <TableCell className="text-xs">{row.ok ? `$${row.cost_usd.toFixed(4)}` : row.error}</TableCell>
                      <TableCell className="text-xs">{row.latency_ms} ms</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : <p className="text-xs text-muted-foreground">{t("settings.providers.usageEmpty")}</p>}
        </CardContent>
      </Card>
    </div>
  )
}
