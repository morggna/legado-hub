import { useState, useEffect, useId, useRef } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, CheckCircle2, Loader2, RefreshCw, Save, Trash2 } from "lucide-react"
import { api, apiErrorMessage } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Switch } from "@/components/ui/switch"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"

const settingsCardClass = "border-slate-200 bg-white shadow-sm"
const settingsInputClass = "h-10 border-slate-200 bg-white shadow-none"
const settingsTabTriggerClass = "data-[state=active]:bg-white data-[state=active]:text-slate-950 data-[state=active]:shadow"
const subscriptionRateFields = [
  ["rateLimitWindowSeconds", "限流窗口（秒）", "搜索、订阅和设置更新共享的计数窗口。", 60],
  ["searchRateLimitPerWindow", "每窗口搜索次数", "每个用户可发起的订阅搜索次数。", 30],
  ["createRateLimitPerWindow", "每窗口订阅次数", "每个用户可发起的订阅创建或恢复次数。", 10],
  ["updateRateLimitPerWindow", "每窗口设置更新次数", "每个用户可修改个人订阅设置的次数。", 60],
] as const

function secondsToMilliseconds(value: unknown, fallbackSeconds: number) {
  const seconds = Number(value ?? fallbackSeconds)
  return Number.isFinite(seconds) ? Math.round(seconds * 1000) : fallbackSeconds * 1000
}

function millisecondsToSeconds(value: string) {
  const milliseconds = Number(value)
  return Number.isFinite(milliseconds) ? milliseconds / 1000 : 0
}

function parseRecord(value: unknown): Record<string, any> {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value)
      return parsed && typeof parsed === "object" ? parsed : {}
    } catch {
      return {}
    }
  }
  return value && typeof value === "object" ? value as Record<string, any> : {}
}

function SettingRow({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col justify-between gap-4 border-b border-slate-100 py-4 last:border-0 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1 pr-4">
        <h4 className="text-sm font-medium text-slate-900">{title}</h4>
        <p className="mt-1 text-sm text-slate-500">{description}</p>
      </div>
      <div className="w-full shrink-0 sm:w-64">{children}</div>
    </div>
  )
}

/** Shared card chrome so every tab panel stacks with the same top edge and spacing. */
function SettingsCard({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <Card className={settingsCardClass}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

const tabPanelClass = "mt-0 space-y-6 outline-none focus-visible:ring-0 focus-visible:ring-offset-0"

interface PrioritySourceOption {
  pluginId: string
  name: string
  official: boolean
  origin: "builtin" | "custom"
}

function PriorityListEditor({ title, description, items, options, optionsReady = true, onChange }: { title: string; description: string; items: string[]; options: PrioritySourceOption[]; optionsReady?: boolean; onChange: (items: string[]) => void }) {
  const editorId = useId()
  const [sourceToAdd, setSourceToAdd] = useState("")
  const sourceById = new Map(options.map((option) => [option.pluginId, option]))
  // Never list uninstalled plugin IDs (e.g. gitignored official app source).
  const visibleItems = items.filter((item) => sourceById.has(item))
  const availableOptions = options.filter((option) => !visibleItems.includes(option.pluginId))

  useEffect(() => {
    // Wait until plugins query settled so an empty options list is intentional.
    if (!optionsReady) return
    if (visibleItems.length === items.length && visibleItems.every((id, index) => id === items[index])) return
    onChange(visibleItems)
  }, [optionsReady, items, visibleItems, onChange])

  const focusAfterUpdate = (selector: string) => {
    setTimeout(() => (document.getElementById(editorId)?.querySelector(selector) as HTMLElement | null)?.focus(), 0)
  }

  const moveItem = (from: number, to: number) => {
    if (to < 0 || to >= visibleItems.length) return
    const next = [...visibleItems]
    ;[next[from], next[to]] = [next[to], next[from]]
    onChange(next)
    focusAfterUpdate(`[data-row-index="${to}"] [data-row-focus]`)
  }

  const removeItem = (index: number) => {
    const next = visibleItems.filter((_, itemIndex) => itemIndex !== index)
    onChange(next)
    focusAfterUpdate(next.length > 0 ? `[data-row-index="${Math.min(index, next.length - 1)}"] [data-row-focus]` : "[data-add-source]")
  }

  const addItem = (pluginId: string) => {
    if (!pluginId || visibleItems.includes(pluginId) || !sourceById.has(pluginId)) return
    onChange([...visibleItems, pluginId])
    setSourceToAdd("")
    focusAfterUpdate(`[data-row-index="${visibleItems.length}"] [data-row-focus]`)
  }

  return (
    <section id={editorId} className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          <p className="mt-1 text-sm text-slate-500">{description}</p>
        </div>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">{visibleItems.length} 个源</span>
      </div>

      {visibleItems.length === 0 ? (
        <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">暂未配置，运行时使用默认顺序。</div>
      ) : (
        <div className="divide-y divide-slate-100 overflow-hidden rounded-md border border-slate-200 bg-white">
          {visibleItems.map((item, index) => {
            const source = sourceById.get(item)
            return (
            <div key={`${item}-${index}`} data-row-index={index} className="flex items-center gap-2 p-3">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-slate-100 text-xs font-semibold tabular-nums text-slate-500">{index + 1}</span>
              <div
                aria-label={`${title}第 ${index + 1} 项`}
                data-row-focus
                tabIndex={-1}
                className="min-w-0 flex-1"
              >
                <div className="truncate text-sm font-medium text-slate-900">{source?.name || item}</div>
                <div className="truncate font-mono text-xs text-slate-400">{item}</div>
              </div>
              <Badge variant="secondary" className="shrink-0 text-[10px]">
                {source?.origin === "custom" ? "自定义" : "内置"}
              </Badge>
              <div className="flex shrink-0 items-center">
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8" aria-label={`将${title}第 ${index + 1} 项上移`} title="上移" disabled={index === 0} onClick={() => moveItem(index, index - 1)}><ArrowUp className="h-4 w-4" /></Button>
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8" aria-label={`将${title}第 ${index + 1} 项下移`} title="下移" disabled={index === visibleItems.length - 1} onClick={() => moveItem(index, index + 1)}><ArrowDown className="h-4 w-4" /></Button>
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8 text-rose-600 hover:bg-rose-50 hover:text-rose-700" aria-label={`删除${title}第 ${index + 1} 项`} title="删除" onClick={() => removeItem(index)}><Trash2 className="h-4 w-4" /></Button>
              </div>
            </div>
            )
          })}
        </div>
      )}

      <select
        data-add-source
        aria-label={`添加${title}`}
        className="h-10 w-full max-w-md rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-700 shadow-none focus:outline-none focus:ring-2 focus:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-60"
        value={sourceToAdd}
        disabled={availableOptions.length === 0}
        onChange={(event) => addItem(event.target.value)}
      >
        <option value="">{availableOptions.length > 0 ? "选择要添加的书源" : "没有可添加的书源"}</option>
        {availableOptions.map((option) => (
          <option key={option.pluginId} value={option.pluginId}>{option.name} ({option.pluginId})</option>
        ))}
      </select>
    </section>
  )
}

export function SettingsPage() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState("reading")
  const [isSaving, setIsSaving] = useState(false)
  const [isSaved, setIsSaved] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordOk, setPasswordOk] = useState(false)

  const { data: settingsData, error: settingsError, refetch: refetchSettings } = useQuery({ queryKey: ["settings"], queryFn: api.settings })
  const { data: aggData, error: aggError, refetch: refetchAggregateSettings } = useQuery({ queryKey: ["aggregateSettings"], queryFn: api.aggregateSettings })
  const { data: lexiconData, error: lexiconError, refetch: refetchLexicon } = useQuery({ queryKey: ["lexiconStatus"], queryFn: api.lexiconStatus })
  const { data: pluginsData, error: pluginsError, isSuccess: pluginsReady, refetch: refetchPlugins } = useQuery({ queryKey: ["plugins"], queryFn: api.plugins })

  const [editedSettings, setEditedSettings] = useState<Record<string, any> | null>(null)
  const [aggForm, setAggForm] = useState<Record<string, any> | null>(null)

  // Keep chrome (title/tabs/save) aligned: reset main scroll when tab changes.
  useEffect(() => {
    const main = document.querySelector("main")
    if (main instanceof HTMLElement) {
      main.scrollTo({ top: 0, behavior: "auto" })
    }
  }, [activeTab])

  useEffect(() => {
    if (isSaved) {
      savedTimer.current = setTimeout(() => setIsSaved(false), 2000)
      return () => { if (savedTimer.current) clearTimeout(savedTimer.current) }
    }
  }, [isSaved])

  const local = editedSettings || settingsData || {}
  const sp = local.sourcePool || {}
  const subscription = local.subscription || {}
  const chapterComment = local.chapterComment || {}
  const readingAccess = local.readingAccess || {}
  const agg = aggForm ?? aggData ?? {}
  const wf = parseRecord(agg.contentWorkflow)
  const sourceOptions: PrioritySourceOption[] = (pluginsData?.items || []).map((plugin: any) => ({
    pluginId: String(plugin.pluginId || ""),
    name: String(plugin.name || plugin.pluginId || "未知书源"),
    official: Boolean(plugin.official),
    origin: plugin.origin ?? "builtin",
  })).filter((plugin: PrioritySourceOption) => plugin.pluginId)

  const setLocal = (patch: any) => {
    setHasChanges(true)
    setEditedSettings((previous) => ({ ...(previous ?? settingsData ?? {}), ...patch }))
  }
  const setAgg = (patch: any) => {
    setHasChanges(true)
    setAggForm((previous) => ({ ...(previous ?? aggData ?? {}), ...patch }))
  }

  const saveSettings = useMutation({
    mutationFn: api.updateSettings,
  })
  const saveAgg = useMutation({ mutationFn: api.updateAggregateSettings })

  const changePassword = useMutation({
    mutationFn: api.auth.changePassword,
    onSuccess: () => { setCurrentPassword(""); setNewPassword(""); setConfirmPassword(""); setPasswordError(null); setPasswordOk(true) },
    onError: (err: any) => { setPasswordError(err?.message || "修改失败") },
  })

  const updateLexicon = useMutation({ mutationFn: api.updateLexicon, onSuccess: () => refetchLexicon() })

  const handleSave = async () => {
    if (!hasChanges || isSaving) return
    setIsSaving(true)
    setSaveError(null)
    setIsSaved(false)
    try {
      // Both endpoints persist app_config.json. Keep the writes ordered and
      // exclude the workflow from the general payload so an older snapshot
      // cannot overwrite the aggregate settings.
      const invalidations: Promise<unknown>[] = []
      if (editedSettings) {
        const localPayload = { ...local }
        delete localPayload.contentWorkflow
        await saveSettings.mutateAsync(localPayload)
        invalidations.push(queryClient.invalidateQueries({ queryKey: ["settings"] }))
      }
      if (aggForm) {
        await saveAgg.mutateAsync(agg)
        invalidations.push(queryClient.invalidateQueries({ queryKey: ["aggregateSettings"] }))
      }
      await Promise.all(invalidations)
      setEditedSettings(null)
      setAggForm(null)
      setIsSaved(true)
      setHasChanges(false)
    } catch (error: any) {
      setSaveError(error?.message || "保存配置失败，请稍后重试。")
    } finally {
      setIsSaving(false)
    }
  }

  const handlePasswordSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordError(null); setPasswordOk(false)
    if (!currentPassword || !newPassword) { setPasswordError("请输入当前密码和新密码"); return }
    if (newPassword !== confirmPassword) { setPasswordError("两次输入的新密码不一致"); return }
    changePassword.mutate({ currentPassword, newPassword })
  }

  return (
    <>
    {/*
      Shared frame for every tab:
      - title + tabs stay mounted (same position)
      - only TabsContent body swaps
      - save bar is fixed and shares the same max-w-4xl column
    */}
    <div className="mx-auto w-full max-w-4xl space-y-6 pb-28">
      <div className="text-center">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">系统设置</h1>
        <p className="mt-1 text-sm text-slate-500">配置 LegadoHub 的核心运行参数。</p>
      </div>

      {(settingsError || aggError || pluginsError || saveError) && (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{saveError || apiErrorMessage(settingsError || aggError || pluginsError, "设置加载失败，请稍后重试。")}</span>
            {(settingsError || aggError || pluginsError) && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => { void Promise.all([refetchSettings(), refetchAggregateSettings(), refetchPlugins()]) }}
              >
                重试
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab} className="gap-6">
        {/* Centered segmented control: background only as wide as the tabs. */}
        <div className="flex justify-center">
          <TabsList className="h-auto w-auto gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1.5 text-slate-500">
            <TabsTrigger className={settingsTabTriggerClass} value="account">账户</TabsTrigger>
            <TabsTrigger className={settingsTabTriggerClass} value="reading">阅读</TabsTrigger>
            <TabsTrigger className={settingsTabTriggerClass} value="sources">书源</TabsTrigger>
            <TabsTrigger className={settingsTabTriggerClass} value="system">系统</TabsTrigger>
          </TabsList>
        </div>

        {/* Content slot: every tab uses the same panel class + card stack. */}
        <div className="min-h-[28rem]">
        <TabsContent value="account" className={tabPanelClass}>
          <SettingsCard title="修改密码" description="定期修改密码有助于保护您的账户安全。">
            <form onSubmit={handlePasswordSubmit}>
              <SettingRow title="当前密码" description="验证您的身份后才能设置新密码。">
                <Input id="current-password" className={settingsInputClass} autoComplete="current-password" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
              </SettingRow>
              <SettingRow title="新密码" description="建议使用较长且不易猜测的密码。">
                <Input id="new-password" className={settingsInputClass} autoComplete="new-password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              </SettingRow>
              <SettingRow title="确认新密码" description="再次输入新密码以确认。">
                <Input id="confirm-password" className={settingsInputClass} autoComplete="new-password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
              </SettingRow>
              {(passwordError || passwordOk) && (
                <div className="pt-4">
                  {passwordError && <Alert variant="destructive"><AlertDescription>{passwordError}</AlertDescription></Alert>}
                  {passwordOk && <Alert><AlertDescription>密码已修改。</AlertDescription></Alert>}
                </div>
              )}
              <div className="flex justify-end pt-4">
                <Button type="submit" variant="secondary" disabled={changePassword.isPending}>
                  {changePassword.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  更新密码
                </Button>
              </div>
            </form>
          </SettingsCard>
        </TabsContent>

        <TabsContent value="reading" className={tabPanelClass}>
          <SettingsCard
            title="公网书源地址"
            description="用于生成专属书源里的公网地址；此处设置优先于部署变量。不拦截访问，公网入口请用雷池或防火墙控制。"
          >
            <SettingRow
              title="公网书源地址"
              description="单个 origin，含协议；非 80/443 请写端口。不要带路径。"
            >
              <Input
                className={settingsInputClass}
                aria-label="公网书源地址"
                placeholder="https://book.example.com:2087"
                value={readingAccess.publicBaseUrl ?? ""}
                onChange={(event) => setLocal({ readingAccess: { ...readingAccess, publicBaseUrl: event.target.value } })}
              />
            </SettingRow>
            <p className="mt-3 text-xs text-slate-500">
              示例：<code className="text-[11px]">https://book.example.com:2087</code>。留空时使用 LEGADOHUB_PUBLIC_BASE_URL，改完立即生效。
            </p>
          </SettingsCard>
          <SettingsCard title="章节评论入口" description="控制聚合书源在支持章节评论协议的阅读客户端中显示哪些入口。">
            <SettingRow title="段评入口" description="在有评论的正文段落末尾显示段评数量。">
              <div className="flex justify-end">
                <Switch
                  aria-label="段评入口"
                  checked={chapterComment.segmentEnabled ?? true}
                  onCheckedChange={(checked) => setLocal({ chapterComment: { ...chapterComment, segmentEnabled: checked } })}
                />
              </div>
            </SettingRow>
            <SettingRow title="页热评入口" description="在当前页右上角显示热评数量，并允许下拉打开本页热评。">
              <div className="flex justify-end">
                <Switch
                  aria-label="页热评入口"
                  checked={chapterComment.pageEnabled ?? true}
                  onCheckedChange={(checked) => setLocal({ chapterComment: { ...chapterComment, pageEnabled: checked } })}
                />
              </div>
            </SettingRow>
            <SettingRow title="本章说入口" description="在章节末尾显示本章说汇总入口。">
              <div className="flex justify-end">
                <Switch
                  aria-label="本章说入口"
                  checked={chapterComment.chapterEnabled ?? true}
                  onCheckedChange={(checked) => setLocal({ chapterComment: { ...chapterComment, chapterEnabled: checked } })}
                />
              </div>
            </SettingRow>
          </SettingsCard>
        </TabsContent>

        <TabsContent value="sources" className={tabPanelClass}>
          <SettingsCard title="并发与超时" description="控制搜索和解析时的并发数量与超时熔断时间。">
            <SettingRow title="最大并发搜索数" description="同时向多少个书源发起搜索请求。过高可能导致内存溢出。">
              <Input className={settingsInputClass} type="number" value={sp.max_concurrency || 3} onChange={(e) => setLocal({ sourcePool: { ...sp, max_concurrency: +e.target.value } })} />
            </SettingRow>
            <SettingRow title="单源超时 (ms)" description="等待一个普通源响应的最长时间。">
              <Input className={settingsInputClass} type="number" value={secondsToMilliseconds(sp.source_timeout_seconds, 20)} onChange={(e) => setLocal({ sourcePool: { ...sp, source_timeout_seconds: millisecondsToSeconds(e.target.value) } })} />
            </SettingRow>
            <SettingRow title="浏览器模式搜索超时 (ms)" description="等待 Headless 浏览器搜索结果。">
              <Input className={settingsInputClass} type="number" value={secondsToMilliseconds(sp.browser_search_timeout_seconds, 60)} onChange={(e) => setLocal({ sourcePool: { ...sp, browser_search_timeout_seconds: millisecondsToSeconds(e.target.value) } })} />
            </SettingRow>
            <SettingRow title="搜索评分过滤" description="低于此分数的搜索结果会被直接丢弃。">
              <Input className={settingsInputClass} type="number" value={local.searchScoreFilter ?? 40} onChange={(e) => setLocal({ searchScoreFilter: +e.target.value })} />
            </SettingRow>
          </SettingsCard>
          <SettingsCard title="网络代理与标识" description="HTTP 请求标识与代理，以及需登录的书源是否参与普通搜索。">
            <SettingRow title="默认 User-Agent" description="访问书源时使用的 HTTP 标识。">
              <Input className={settingsInputClass} value={sp.default_user_agent || ""} onChange={(e) => setLocal({ sourcePool: { ...sp, default_user_agent: e.target.value } })} />
            </SettingRow>
            <SettingRow title="启用网络代理" description="允许标记为强制代理的书源使用下方代理地址。">
              <div className="flex items-center justify-end gap-2">
                <Switch checked={sp.proxy?.enabled || false} onCheckedChange={(c) => setLocal({ sourcePool: { ...sp, proxy: { ...(sp.proxy || {}), enabled: c } } })} />
                <span className="text-sm text-slate-600">启用</span>
              </div>
            </SettingRow>
            <SettingRow title="代理 URL (Proxy)" description="配置 HTTP/SOCKS 代理用于访问受限书源。">
              <Input className={settingsInputClass} value={sp.proxy?.url || ""} onChange={(e) => setLocal({ sourcePool: { ...sp, proxy: { ...(sp.proxy || {}), url: e.target.value } } })} />
            </SettingRow>
            <SettingRow title="直连失败后自动代理" description="普通书源遇到 403、429、连接失败或超时时，再通过代理重试。">
              <div className="flex items-center justify-end gap-2">
                <Switch checked={sp.proxy?.allowAutoRetry || false} onCheckedChange={(c) => setLocal({ sourcePool: { ...sp, proxy: { ...(sp.proxy || {}), allowAutoRetry: c } } })} />
                <span className="text-sm text-slate-600">启用</span>
              </div>
            </SettingRow>
            <SettingRow title="需登录的书源参与普通搜索" description="是否在常规聚合搜索中包含需登录的书源。">
              <div className="flex items-center justify-end gap-2">
                <Switch checked={sp.officialSourceInNormalSearch || false} onCheckedChange={(c) => setLocal({ sourcePool: { ...sp, officialSourceInNormalSearch: c } })} />
                <span className="text-sm text-slate-600">启用</span>
              </div>
            </SettingRow>
          </SettingsCard>
          <SettingsCard title="书源优先级" description="列表顺序就是处理顺序，排在上方的书源会被优先使用。">
            <div className="space-y-8">
              <PriorityListEditor
                title="认证书源优先级"
                description="用于目录对齐和元数据抓取。"
                items={Array.isArray(wf.primarySourcePriority) ? wf.primarySourcePriority.map(String) : []}
                options={sourceOptions.filter((source) => source.official)}
                optionsReady={pluginsReady}
                onChange={(items) => setAgg({ contentWorkflow: { ...wf, primarySourcePriority: items } })}
              />
              <div className="border-t border-slate-100 pt-8">
                <PriorityListEditor
                  title="补全源优先级"
                  description="用于补全 VIP 预览或读取失败的章节。"
                  items={Array.isArray(wf.candidateSourcePriority) ? wf.candidateSourcePriority.map(String) : []}
                  options={sourceOptions.filter((source) => !source.official)}
                  optionsReady={pluginsReady}
                  onChange={(items) => setAgg({ contentWorkflow: { ...wf, candidateSourcePriority: items } })}
                />
              </div>
            </div>
          </SettingsCard>
        </TabsContent>

        <TabsContent value="system" className={tabPanelClass}>
          <SettingsCard title="订阅配额" description="共享入库资源的全局边界，仅管理员可调整。">
            <SettingRow title="每用户活跃订阅上限" description="统计处理中和已暂停的个人订阅。">
              <Input
                className={settingsInputClass}
                type="number"
                aria-label="每用户活跃订阅上限"
                min={1}
                step={1}
                value={subscription.maxActivePerUser ?? 100}
                onChange={(event) => setLocal({ subscription: { ...subscription, maxActivePerUser: Number(event.target.value) } })}
              />
            </SettingRow>
            <SettingRow title="每日新建共享书上限" description="单个用户在 24 小时内可触发的新共享书数量。">
              <Input
                className={settingsInputClass}
                type="number"
                aria-label="每日新建共享书上限"
                min={1}
                step={1}
                value={subscription.maxNewSharedBooksPerDay ?? 10}
                onChange={(event) => setLocal({ subscription: { ...subscription, maxNewSharedBooksPerDay: Number(event.target.value) } })}
              />
            </SettingRow>
            <SettingRow title="全局待入库书上限" description="尚未产出首批可读章节的共享处理任务数量。">
              <Input
                className={settingsInputClass}
                type="number"
                aria-label="全局待入库书上限"
                min={1}
                step={1}
                value={subscription.maxGlobalProvisioningBooks ?? 20}
                onChange={(event) => setLocal({ subscription: { ...subscription, maxGlobalProvisioningBooks: Number(event.target.value) } })}
              />
            </SettingRow>
          </SettingsCard>
          <SettingsCard title="请求频率" description="按用户独立计数，进程重启后自动清空。">
            {subscriptionRateFields.map(([field, title, description, fallback]) => (
              <SettingRow key={field} title={title} description={description}>
                <Input
                  className={settingsInputClass}
                  type="number"
                  aria-label={title}
                  min={1}
                  step={1}
                  value={subscription[field] ?? fallback}
                  onChange={(event) => setLocal({ subscription: { ...subscription, [field]: Number(event.target.value) } })}
                />
              </SettingRow>
            ))}
          </SettingsCard>
          <SettingsCard title="聚合策略" description="配置候选源数量、检查间隔等聚合运行参数。">
            <SettingRow title="候选书源数量" description="为每本书保留最多几个高质量备选源用于容灾。">
              <Input className={settingsInputClass} type="number" value={wf.sourceCandidateLimit || 6} onChange={(e) => setAgg({ contentWorkflow: { ...wf, sourceCandidateLimit: +e.target.value } })} />
            </SettingRow>
            <SettingRow title="自动更新间隔(分钟)" description="后台自动检查书籍更新的频率。">
              <Input className={settingsInputClass} type="number" value={wf.aggregateCheckIntervalMinutes ?? 30} onChange={(e) => setAgg({ contentWorkflow: { ...wf, aggregateCheckIntervalMinutes: +e.target.value } })} />
            </SettingRow>
          </SettingsCard>
          <SettingsCard title="净化词库管理" description="用于修复乱码、屏蔽词和谐以及统一内容格式。">
            <div className="rounded-lg border border-slate-100 bg-slate-50 p-4">
              <div className="mb-4 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
                <div>
                  <h4 className="text-sm font-bold text-slate-800">当前词库状态</h4>
                  {lexiconData?.commitSha && <p className="mt-1 font-mono text-xs text-slate-500">Commit: {lexiconData.commitSha.slice(0, 7)}</p>}
                </div>
                <Button variant="outline" size="sm" className="bg-white" onClick={() => updateLexicon.mutate()} disabled={updateLexicon.isPending}>
                  {updateLexicon.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <RefreshCw className="mr-2 h-4 w-4" /> 强制同步
                </Button>
              </div>
              <div className="grid grid-cols-2 gap-4 border-t border-slate-200 py-4 md:grid-cols-4">
                <div><div className="text-xs text-slate-400">版本</div><div className="mt-0.5 text-sm font-medium text-slate-800">{lexiconData?.commitSha ? lexiconData.commitSha.slice(0, 7) : "未安装"}</div></div>
                <div><div className="text-xs text-slate-400">规则文件数</div><div className="mt-0.5 text-sm font-medium text-slate-800">{lexiconData?.fileCount ?? "-"}</div></div>
                <div><div className="text-xs text-slate-400">词条总数</div><div className="mt-0.5 text-sm font-medium text-slate-800">{lexiconData?.wordCount ?? "-"}</div></div>
                <div><div className="text-xs text-slate-400">最后更新</div><div className="mt-0.5 text-sm font-medium text-slate-800">{lexiconData?.updatedAt ? new Date(lexiconData.updatedAt).toLocaleString() : "-"}</div></div>
              </div>
              {lexiconError && (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-rose-600">
                  <span>词库状态加载失败：{apiErrorMessage(lexiconError, "请稍后重试。")}</span>
                  <Button type="button" size="sm" variant="outline" onClick={() => { void refetchLexicon() }}>重试</Button>
                </div>
              )}
              {updateLexicon.error && <p className="mt-3 text-sm text-rose-600">词库同步失败：{apiErrorMessage(updateLexicon.error, "请稍后重试。")}</p>}
            </div>
          </SettingsCard>
        </TabsContent>
        </div>
      </Tabs>
    </div>

      {/*
        Save bar mirrors Layout main geometry:
        fixed over the main column (md:left-64), then max-w-6xl → max-w-4xl,
        same horizontal padding as <main class="p-6 md:p-8">.
      */}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-20 md:left-64">
        <div className="pointer-events-none mx-auto w-full max-w-6xl px-6 pb-4 pt-2 md:px-8">
          <div className="pointer-events-auto mx-auto flex w-full max-w-4xl items-center justify-end gap-3 rounded-xl border border-slate-200 bg-white/95 px-4 py-3 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-white/90">
            {isSaved && (
              <span className="mr-auto flex items-center text-sm text-emerald-600">
                <CheckCircle2 className="mr-1.5 h-4 w-4" /> 已保存
              </span>
            )}
            <Button
              onClick={handleSave}
              disabled={!hasChanges || isSaving}
              className={`min-w-[120px] ${hasChanges ? "bg-blue-600 shadow-md hover:bg-blue-700" : "bg-slate-800"}`}
            >
              {isSaving ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> 保存中</> : <><Save className="mr-2 h-4 w-4" /> 保存配置</>}
            </Button>
          </div>
        </div>
      </div>
    </>
  )
}
