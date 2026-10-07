import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { SettingsPage } from "./SettingsPage"

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    settings: vi.fn(),
    updateSettings: vi.fn(),
    aggregateSettings: vi.fn(),
    updateAggregateSettings: vi.fn(),
    plugins: vi.fn(),
    lexiconStatus: vi.fn(),
    updateLexicon: vi.fn(),
    auth: { changePassword: vi.fn() },
  },
}))

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  )
}

describe("SettingsPage subscription policy", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.settings as any).mockResolvedValue({
      sourcePool: {
        proxy: { enabled: false, url: "", allowAutoRetry: false },
        max_concurrency: 20,
        source_timeout_seconds: 8,
        overall_search_timeout_seconds: 120,
        browser_source_timeout_seconds: 30,
        browser_search_timeout_seconds: 30,
        default_user_agent: "test-agent",
        officialSourceInNormalSearch: false,
      },
      searchScoreFilter: 100,
      searchConfig: {
        overallTimeoutSeconds: 120,
        firstResultTimeoutSeconds: 5,
        sourceTimeoutSeconds: 8,
        cacheTtlSeconds: 600,
      },
      contentWorkflow: {},
      subscription: {
        maxActivePerUser: 100,
        maxNewSharedBooksPerDay: 10,
        maxGlobalProvisioningBooks: 20,
        rateLimitWindowSeconds: 60,
        searchRateLimitPerWindow: 30,
        createRateLimitPerWindow: 10,
        updateRateLimitPerWindow: 60,
      },
      chapterComment: {
        segmentEnabled: true,
        pageEnabled: true,
        chapterEnabled: true,
      },
      readingAccess: {
        publicBaseUrl: "",
      },
    })
    ;(api.aggregateSettings as any).mockResolvedValue({ contentWorkflow: {} })
    ;(api.lexiconStatus as any).mockResolvedValue({})
    ;(api.plugins as any).mockResolvedValue({
      items: [
        { pluginId: "qidian_com_app", name: "起点中文网 (App)", official: true },
        { pluginId: "qidian_com_web", name: "起点中文网 (Web)", official: true },
        { pluginId: "fanqie_novel", name: "番茄小说", official: true },
        { pluginId: "xbiquzw_net", name: "笔趣阁", official: false },
        { pluginId: "new_candidate", name: "新补全源", official: false },
      ],
    })
    ;(api.updateSettings as any).mockResolvedValue({ saved: true })
    ;(api.updateAggregateSettings as any).mockResolvedValue({ saved: true })
  })

  it("saves administrator subscription quotas through the existing settings flow", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("tab", { name: "系统" }))
    const activeLimit = screen.getByLabelText("每用户活跃订阅上限")
    const searchLimit = screen.getByLabelText("每窗口搜索次数")
    await user.clear(activeLimit)
    await user.type(activeLimit, "23")
    await user.clear(searchLimit)
    await user.type(searchLimit, "12")
    await user.click(screen.getByRole("button", { name: "保存配置" }))

    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1))
    const payload = (api.updateSettings as any).mock.calls[0][0]
    expect(payload.subscription).toEqual({
      maxActivePerUser: 23,
      maxNewSharedBooksPerDay: 10,
      maxGlobalProvisioningBooks: 20,
      rateLimitWindowSeconds: 60,
      searchRateLimitPerWindow: 12,
      createRateLimitPerWindow: 10,
      updateRateLimitPerWindow: 60,
    })
    expect(payload.searchConfig.sourceTimeoutSeconds).toBe(8)
    expect(payload.contentWorkflow).toBeUndefined()
  })

  it("refetches both settings queries from the load error", async () => {
    const user = userEvent.setup()
    ;(api.settings as any)
      .mockRejectedValueOnce(new Error("设置接口不可用"))
      .mockResolvedValueOnce({ sourcePool: {}, subscription: {} })
    renderPage()

    expect(await screen.findByText("设置接口不可用")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => expect(api.settings).toHaveBeenCalledTimes(2))
    expect(api.aggregateSettings).toHaveBeenCalledTimes(2)
  })

  it("saves the three reader comment entry switches", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("tab", { name: "阅读" }))
    await user.click(screen.getByRole("switch", { name: "段评入口" }))
    await user.click(screen.getByRole("switch", { name: "页热评入口" }))
    await user.click(screen.getByRole("button", { name: "保存配置" }))

    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1))
    const payload = (api.updateSettings as any).mock.calls[0][0]
    expect(payload.chapterComment).toEqual({
      segmentEnabled: false,
      pageEnabled: false,
      chapterEnabled: true,
    })
  })

  it("saves the reading public base allowlist URL", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("tab", { name: "阅读" }))
    expect(screen.getByRole("heading", { name: "公网书源地址" })).toBeInTheDocument()
    const baseInput = screen.getByLabelText("公网书源地址")
    await user.clear(baseInput)
    await user.type(baseInput, "https://book.example.com:2087")
    await user.click(screen.getByRole("button", { name: "保存配置" }))

    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1))
    const payload = (api.updateSettings as any).mock.calls[0][0]
    expect(payload.readingAccess).toEqual({
      publicBaseUrl: "https://book.example.com:2087",
    })
  })

  it("reorders source priorities and saves the existing array contract", async () => {
    const user = userEvent.setup()
    ;(api.aggregateSettings as any).mockResolvedValue({
      contentWorkflow: {
        primarySourcePriority: ["qidian_com_app", "qidian_com_web", "fanqie_novel"],
        candidateSourcePriority: ["xbiquzw_net"],
      },
    })
    renderPage()

    await user.click(await screen.findByRole("tab", { name: "书源" }))
    const moveButton = screen.getByRole("button", { name: "将认证书源优先级第 1 项下移" })
    await user.click(moveButton)
    await waitFor(() => expect(screen.getByLabelText("认证书源优先级第 2 项")).toHaveFocus())
    expect(screen.getByLabelText("认证书源优先级第 2 项")).toHaveTextContent("qidian_com_app")
    expect(screen.queryByRole("textbox", { name: "认证书源优先级第 2 项" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "保存配置" }))

    await waitFor(() => expect(api.updateAggregateSettings).toHaveBeenCalledTimes(1))
    const payload = (api.updateAggregateSettings as any).mock.calls[0][0]
    expect(payload.contentWorkflow.primarySourcePriority).toEqual(["qidian_com_web", "qidian_com_app", "fanqie_novel"])
    expect(payload.contentWorkflow.candidateSourcePriority).toEqual(["xbiquzw_net"])
  })

  it("adds a priority from the installed source list", async () => {
    const user = userEvent.setup()
    ;(api.aggregateSettings as any).mockResolvedValue({
      contentWorkflow: { primarySourcePriority: ["qidian_com_app"], candidateSourcePriority: [] },
    })
    renderPage()

    await user.click(await screen.findByRole("tab", { name: "书源" }))
    await user.selectOptions(screen.getByRole("combobox", { name: "添加补全源优先级" }), "new_candidate")
    expect(screen.getByLabelText("补全源优先级第 1 项")).toHaveTextContent("new_candidate")
    await user.click(screen.getByRole("button", { name: "保存配置" }))

    await waitFor(() => expect(api.updateAggregateSettings).toHaveBeenCalledTimes(1))
    const payload = (api.updateAggregateSettings as any).mock.calls[0][0]
    expect(payload.contentWorkflow.candidateSourcePriority).toEqual(["new_candidate"])
  })
})
