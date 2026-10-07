import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { directRequest } from "@/lib/direct-api"
import { Plugins } from "./Plugins"

vi.mock("@/lib/direct-api", () => ({ directRequest: vi.fn() }))

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    plugins: vi.fn(),
    pingAllPlugins: vi.fn(),
    batchEnablePlugins: vi.fn(),
    officialSources: vi.fn(),
  },
}))

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Plugins />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("Plugins", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.plugins as any).mockResolvedValue({
      items: [
        { pluginId: "source-1", name: "书源一", author: "Yunwei", version: "1.2.3", enabled: true, official: false, origin: "builtin", accessType: "Browser", capabilities: ["chapter_reviews"], health: { pingStatus: "reachable", pingLatencyMs: 10 } },
        { pluginId: "source-2", name: "书源二", author: "Yunwei", enabled: true, official: false, origin: "builtin", health: { pingStatus: "unreachable", pingLatencyMs: 20 } },
        { pluginId: "official-1", name: "官方源一", author: "Yunwei", enabled: true, official: true, origin: "builtin", capabilities: ["auth"] },
        { pluginId: "custom-1", name: "自定义源一", enabled: true, origin: "custom", capabilities: ["search"] },
      ],
    })
    ;(api.officialSources as any).mockResolvedValue({items:[]})
    ;(api.pingAllPlugins as any).mockResolvedValue({ results: [] })
    ;(api.batchEnablePlugins as any).mockResolvedValue({ results: [] })
  })

  it("uses Ping as the only source health signal", async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText("50.0%")).toBeInTheDocument()
    expect(screen.getByTestId("source-stats")).toBeInTheDocument()
    expect(screen.getByText("2/3 已测")).toBeInTheDocument()
    expect(screen.getAllByText("作者: Yunwei")).toHaveLength(3)
    expect(screen.queryByText(/Smoke|冒烟|测试通过率/)).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/搜索书源名称/)).not.toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "全选当前书源" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "插件标识 (ID)" })).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "格式/分类" })).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "激活状态" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "详情与检测" })).not.toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "内置书源" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "自定义书源" })).toBeInTheDocument()
    expect(screen.getByTestId("official-sources-table-boundary")).toContainElement(screen.getByRole("tablist", { name: "书源类型" }))
    expect(screen.getByRole("table")).toHaveClass("table-fixed")
    expect(screen.getByRole("columnheader", { name: "解析能力" })).toHaveClass("text-center")
    expect(screen.getByRole("columnheader", { name: "Ping" })).toHaveClass("text-center")
    expect(screen.getByText("章评")).toBeInTheDocument()
    const sourceName = screen.getByText("书源一")
    const sourceNameCell = sourceName.closest("td")
    expect(sourceName.nextElementSibling).toHaveTextContent("Browser")
    expect(sourceNameCell).toHaveTextContent("作者: Yunwei")
    expect(sourceNameCell).toHaveTextContent("版本: v1.2.3")
    expect(sourceNameCell).toHaveTextContent("Browser")
    expect(screen.queryByText("chapter_reviews")).not.toBeInTheDocument()
    expect(screen.getByText("10ms")).toBeInTheDocument()
    expect(screen.getByText("不可达")).toBeInTheDocument()
    expect(screen.queryByText("可达")).not.toBeInTheDocument()
    expect(screen.queryByText("状态:")).not.toBeInTheDocument()
    expect(screen.queryByText("延时:")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Ping 全部" }))
    await waitFor(() => expect(api.pingAllPlugins).toHaveBeenCalledWith(["source-1", "source-2", "official-1"]))
  })

  it("runs batch actions from the shared table header selection", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("checkbox", { name: "全选当前书源" }))
    expect(screen.getByText("已选 3 项")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "批量启用" }))

    await waitFor(() => expect(api.batchEnablePlugins).toHaveBeenCalledWith(["source-1", "source-2", "official-1"], true))
  })

  it("retries the plugin list after a transient load failure", async () => {
    const user = userEvent.setup()
    ;(api.plugins as any)
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({ items: [] })
    renderPage()

    await user.click(await screen.findByRole("button", { name: "重试" }))

    await waitFor(() => expect(api.plugins).toHaveBeenCalledTimes(2))
    expect(await screen.findByText("暂无书源。")).toBeInTheDocument()
  })

  it("groups by builtin versus custom while retaining built-in authentication", async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText("官方源一")).toBeInTheDocument()
    expect(screen.getByRole("button", {name:"登录"})).toBeInTheDocument()
    await user.click(screen.getByRole("tab", { name: "自定义书源" }))
    expect(await screen.findByText("自定义源一")).toBeInTheDocument()
    expect(screen.queryByText("官方源一")).not.toBeInTheDocument()
    expect(screen.getByTestId("source-stats")).toBeInTheDocument()
    expect(screen.getByRole("tablist", { name: "书源类型" })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText("搜索书源名称, ID, 或贡献者/作者...")).not.toBeInTheDocument()
  })

  it("manages the attachment account from its custom plugin row", async () => {
    ;(api.plugins as any).mockResolvedValue({items: [{pluginId: "txtnovel_vip", name: "书香门第（附件）", origin: "custom", category: "completed", attachmentSource: true, enabled: true, capabilities: ["search", "full_book", "auth"]}]})
    ;(directRequest as any).mockResolvedValue({bound: true, username: "forum-user", enabled: true})
    const user = userEvent.setup()
    renderPage()
    await screen.findByText("暂无书源。")
    await user.click(screen.getByRole("tab", {name: "自定义书源"}))
    expect(await screen.findByText("书香门第（附件）")).toBeInTheDocument()
    expect(await screen.findByText("forum-user")).toBeInTheDocument()
    expect(screen.getByText("整本下载")).toBeInTheDocument()
    expect(screen.queryByRole("button", {name: "登录"})).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", {name: "管理账号"}))
    expect(await screen.findByRole("dialog")).toHaveTextContent("已绑定：forum-user")
    expect(screen.getByRole("button", {name: "解除绑定"})).toBeInTheDocument()
  })
})
