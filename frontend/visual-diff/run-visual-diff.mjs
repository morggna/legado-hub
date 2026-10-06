import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { mkdir, readFile, writeFile } from "node:fs/promises"
import { createServer } from "node:net"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "playwright"

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendDir = resolve(__dirname, "..")
const baselineDir = resolve(__dirname, "baseline")
const outputRoot = resolve(__dirname, "output")
const updateBaseline = process.argv.includes("--update-baseline")
const minimumSimilarity = 0.98

const ports = { current: 5177 }
const npmCmd = process.platform === "win32" ? "npm.cmd" : "npm"
const useShell = process.platform === "win32"

const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
]

const pages = [
  { id: "combined-login", title: "统一账号登录", currentPath: "/login", scenario: {role: "anonymous", entrypoint: "combined"} },
  { id: "direct-search", title: "第三方直接阅读", currentPath: "/console/search", scenario: {role: "user", entrypoint: "combined"} },
  { id: "direct-shelf", title: "个人书架", currentPath: "/console/library", scenario: {role: "user", entrypoint: "combined"} },
  { id: "direct-reader", title: "按需章节阅读", currentPath: "/console/library/fixture-book", scenario: {role: "user", entrypoint: "combined"} },
  {
    id: "login",
    title: "登录页",
    currentPath: "/login",
    scenario: { role: "anonymous" },
  },
  {
    id: "login-error",
    title: "登录失败",
    currentPath: "/login",
    scenario: { role: "anonymous", entrypoint: "admin", loginError: true },
    prepare: async (page) => {
      await page.getByLabel("密码").fill("invalid-password")
      await page.getByRole("button", { name: "登录", exact: true }).click()
      await page.getByRole("alert").waitFor()
    },
  },
  {
    id: "dashboard-admin",
    title: "管理员仪表盘",
    currentPath: "/console",
    scenario: { role: "admin" },
  },
  {
    id: "dashboard-user",
    title: "用户仪表盘",
    currentPath: "/console",
    scenario: { role: "user" },
  },
  {
    id: "admin-redirect-user",
    title: "普通用户权限回退",
    currentPath: "/console/plugins",
    scenario: { role: "user" },
  },
  {
    id: "subscriptions-results",
    title: "订阅搜索结果",
    currentPath: "/console/admin/subscription",
    scenario: { role: "admin" },
    prepare: async (page) => {
      await page.getByPlaceholder(/搜索你想看的小说或作者/).fill("深海")
      await page.keyboard.press("Enter")
      await page.waitForTimeout(1800)
    },
  },
  {
    id: "subscriptions-admin-logs",
    title: "管理员订阅事件日志",
    currentPath: "/console/admin/subscription",
    scenario: { role: "admin" },
    prepare: async (page) => {
      await page.getByPlaceholder(/搜索你想看的小说或作者/).fill("深海")
      await page.keyboard.press("Enter")
      await page.waitForTimeout(1800)
      await page.getByRole("button", { name: "查看事件日志" }).click()
    },
  },
  {
    id: "library",
    title: "管理员书库",
    currentPath: "/console/admin/library",
    scenario: { role: "admin" },
  },
  {
    id: "library-user-empty",
    title: "用户书库空态",
    currentPath: "/console/library",
    scenario: { role: "user", library: "empty" },
  },
  {
    id: "book-detail",
    title: "书籍详情",
    currentPath: "/console/admin/library/book-2",
    scenario: { role: "admin" },
    prepare: async (page) => {
      await assertMobileHorizontalScroll(page, "chapter-table-boundary")
    },
  },
  {
    id: "book-detail-admin-logs",
    title: "管理员书籍详情日志",
    currentPath: "/console/admin/library/book-2",
    scenario: { role: "admin" },
    preserveScroll: true,
    prepare: async (page) => {
      await assertMobileHorizontalScroll(page, "candidate-sources-table-boundary")
      await assertMobileHorizontalScroll(page, "chapter-table-boundary")
      await page.getByText(/rate limit exceeded/).waitFor()
      const scrollTop = await page.locator("main").evaluate((element) => element.scrollTop)
      if (scrollTop > 1) throw new Error(`book detail unexpectedly scrolled to ${scrollTop}`)
      await page.getByText("实时日志", { exact: true }).scrollIntoViewIfNeeded()
    },
  },
  {
    id: "chapter-detail",
    title: "章节详情",
    currentPath: "/console/library/book-2/chapters/chapter-1",
    scenario: { role: "admin" },
  },
  {
    id: "search-workbench",
    title: "搜索工作台",
    currentPath: "/console/admin/search",
    scenario: { role: "admin" },
    prepare: async (page) => {
      await page.getByPlaceholder(/输入测试关键词/).fill("深海")
      await page.getByRole("button", { name: /调试/ }).click()
      await page.waitForTimeout(500)
    },
  },
  {
    id: "sources",
    title: "书源管理",
    currentPath: "/console/plugins",
    scenario: { role: "admin" },
  },
  {
    id: "sources-empty",
    title: "书源筛选空态",
    currentPath: "/console/plugins",
    scenario: { role: "admin", plugins: "empty" },
  },
  {
    id: "official-sources",
    title: "官方源管理",
    currentPath: "/console/plugins?tab=official",
    scenario: { role: "admin" },
    prepare: async (page) => {
      await assertMobileHorizontalScroll(page, "official-sources-table-boundary")
    },
  },
  {
    id: "official-sources-empty",
    title: "官方源空态",
    currentPath: "/console/official-sources",
    scenario: { role: "admin", officialSources: "empty" },
  },
  {
    id: "official-sources-error",
    title: "官方源错误态",
    currentPath: "/console/plugins?tab=official",
    scenario: { role: "admin", officialSources: "error" },
  },
  {
    id: "official-sources-login",
    title: "官方源登录",
    currentPath: "/console/plugins?tab=official",
    scenario: { role: "admin" },
    prepare: async (page) => {
      await page.getByRole("button", { name: "登录", exact: true }).click()
      await page.getByRole("dialog").waitFor()
    },
  },
  {
    id: "settings",
    title: "系统设置",
    currentPath: "/console/settings",
    scenario: { role: "admin" },
  },
  {
    id: "settings-priority",
    title: "优先级设置",
    currentPath: "/console/settings",
    scenario: { role: "admin" },
    prepare: async (page) => {
      await page.getByRole("tab", { name: "书源" }).click()
    },
  },
  {
    id: "users",
    title: "用户管理",
    currentPath: "/console/users",
    scenario: { role: "admin" },
  },
  {
    id: "mobile-nav-admin",
    title: "移动端管理员导航",
    currentPath: "/console",
    scenario: { role: "admin" },
    viewports: ["mobile"],
    prepare: async (page) => {
      await page.getByRole("button", { name: "打开导航菜单" }).click()
      await page.getByRole("menu").waitFor()
    },
  },
]

const now = new Date()
  .toISOString()
  .replace(/[:.]/g, "-")
  .replace("T", "_")
  .replace("Z", "")
const outputDir = join(outputRoot, now)

function coverFixture(title, background, accent) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="180" height="240" viewBox="0 0 180 240"><rect width="180" height="240" fill="${background}"/><rect x="12" y="12" width="156" height="216" fill="none" stroke="${accent}" stroke-width="2"/><path d="M28 48h124M28 192h124" stroke="${accent}" stroke-width="2" opacity=".7"/><text x="90" y="112" text-anchor="middle" fill="#fff" font-family="sans-serif" font-size="24" font-weight="700">${title.slice(0, 4)}</text><text x="90" y="145" text-anchor="middle" fill="${accent}" font-family="sans-serif" font-size="13">LEGADO HUB</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

const books = [
  {
    aggregateBookId: "book-1",
    id: "1",
    displayName: "深海余烬",
    displayAuthor: "远瞳",
    name: "深海余烬",
    author: "远瞳",
    coverUrl: coverFixture("深海余烬", "#0f766e", "#fbbf24"),
    intro:
      "在那一天，浓雾封锁了一切。在那一天，他成为了一艘幽灵船的船长。在那一天，他跨过浓雾，直面了一个被彻底颠覆而又支离破碎的世界。",
    wordCount: "320万字",
    totalChapters: 812,
    processedChapters: 812,
    visibleProcessedChapters: 812,
    failedChapters: 0,
    status: "completed",
    bookStatus: "ongoing",
    lastChapterTitle: "第812章 归来",
    primarySourceName: "起点中文网",
  },
  {
    aggregateBookId: "book-2",
    id: "2",
    displayName: "道诡异仙",
    displayAuthor: "狐尾的笔",
    name: "道诡异仙",
    author: "狐尾的笔",
    coverUrl: coverFixture("道诡异仙", "#7f1d1d", "#fca5a5"),
    intro:
      "诡异的天道，异常的仙佛，是真？是假？陷入迷惘的李火旺无法分辨。可让他无法分辨的不仅仅只是这些。还有他自己，他病了，病的很重。",
    wordCount: "280万字",
    totalChapters: 1100,
    processedChapters: 540,
    visibleProcessedChapters: 540,
    failedChapters: 50,
    status: "active",
    bookStatus: "completed",
    lastChapterTitle: "第540章 坐忘道",
    primarySourceName: "起点中文网",
  },
  {
    aggregateBookId: "book-3",
    id: "3",
    displayName: "神秘复苏",
    displayAuthor: "佛前献花",
    name: "神秘复苏",
    author: "佛前献花",
    coverUrl: coverFixture("神秘复苏", "#312e81", "#c4b5fd"),
    intro: "五浊恶世，地狱已空，厉鬼复苏，人间如狱。",
    wordCount: "530万字",
    totalChapters: 1540,
    processedChapters: 300,
    visibleProcessedChapters: 300,
    failedChapters: 1,
    status: "error",
    bookStatus: "completed",
    lastChapterTitle: "第300章 鬼眼",
    primarySourceName: "起点中文网",
  },
  {
    aggregateBookId: "book-4",
    id: "4",
    displayName: "黎明之剑",
    displayAuthor: "远瞳",
    name: "黎明之剑",
    author: "远瞳",
    coverUrl: coverFixture("黎明之剑", "#1e3a5f", "#fde68a"),
    intro:
      "高文穿越了，但穿越的时候稍微出了点问题。在某个异界大陆上空飘了十几万年之后，他觉得自己可能需要一具身体。",
    wordCount: "450万字",
    totalChapters: 1600,
    processedChapters: 1600,
    visibleProcessedChapters: 1600,
    failedChapters: 0,
    status: "archived",
    bookStatus: "completed",
    lastChapterTitle: "尾声",
    primarySourceName: "纵横中文网",
  },
]

const searchCards = [
  {
    candidateId: "1",
    aggregateBookId: "book-1",
    name: "深海余烬",
    author: "远瞳",
    coverUrl: books[0].coverUrl,
    intro: books[0].intro,
    wordCount: "320万字",
    chapterCount: 812,
    completed: false,
    alreadyIngested: true,
    sourceCount: 2,
    sourceSummary: [
      { sourceName: "起点中文网(App)" },
      { sourceName: "起点中文网(Web)" },
    ],
  },
  {
    candidateId: "2",
    aggregateBookId: "book-2",
    name: "道诡异仙",
    author: "狐尾的笔",
    coverUrl: books[1].coverUrl,
    intro: books[1].intro,
    wordCount: "280万字",
    chapterCount: 1100,
    completed: true,
    alreadyIngested: false,
    sourceSummary: [{ sourceName: "起点中文网" }],
  },
  {
    candidateId: "3",
    name: "大奉打更人",
    author: "卖报小郎君",
    coverUrl: coverFixture("大奉打更", "#713f12", "#fef3c7"),
    intro: "这个世界，有儒；有道；有佛；有妖；有术士。",
    wordCount: "480万字",
    chapterCount: 1205,
    completed: true,
    alreadyIngested: false,
    sourceSummary: [{ sourceName: "起点中文网" }],
  },
  {
    candidateId: "4",
    name: "赤心巡天",
    author: "情何以甚",
    coverUrl: coverFixture("赤心巡天", "#9f1239", "#fecdd3"),
    intro: "山河千里写伏尸，乾坤百年描饿殍。天地至公如无情，我有赤心一颗，以巡天。",
    wordCount: "650万字",
    chapterCount: 2150,
    completed: false,
    alreadyIngested: true,
    aggregateBookId: "book-4",
    sourceSummary: [{ sourceName: "起点中文网" }],
  },
]

const plugins = [
  {
    pluginId: "com.qidian.sandbox",
    name: "起点中文网 (官方备份)",
    accessType: "JSON",
    capabilities: ["search", "detail", "toc", "chapter", "auth"],
    enabled: true,
    official: false,
    author: "Yunwei",
    tags: ["小说"],
    version: "1.4.2",
    health: { pingStatus: "reachable", pingLatencyMs: 32 },
  },
  {
    pluginId: "com.biquge.general",
    name: "笔趣阁 (通用多路合并)",
    accessType: "HTML",
    capabilities: ["search", "detail", "toc", "chapter"],
    enabled: true,
    official: false,
    author: "Yunwei",
    tags: ["小说"],
    version: "2.1.0",
    health: { pingStatus: "reachable", pingLatencyMs: 124 },
  },
  {
    pluginId: "com.copymanga",
    name: "拷贝漫画 (高清镜像)",
    accessType: "JSON",
    capabilities: ["search", "detail", "toc", "chapter"],
    enabled: true,
    official: false,
    author: "Yunwei",
    tags: ["漫画"],
    version: "1.0.5",
    health: { pingStatus: "reachable", pingLatencyMs: 184 },
  },
  {
    pluginId: "net.wenku8",
    name: "轻小说文库 (Wenku8)",
    accessType: "HTML",
    capabilities: ["search", "detail", "toc", "chapter", "auth"],
    enabled: true,
    official: false,
    author: "Yunwei",
    tags: ["轻小说"],
    version: "1.1.2",
    health: { pingStatus: "reachable", pingLatencyMs: 245 },
  },
  {
    pluginId: "com.tadu",
    name: "塔读文学 (免广告规则)",
    accessType: "JSON",
    capabilities: ["search", "detail", "toc"],
    enabled: false,
    official: false,
    author: "Yunwei",
    tags: ["小说"],
    version: "1.0.1",
    health: { pingStatus: "unknown", pingLatencyMs: 0 },
  },
  {
    pluginId: "net.unknown.novel",
    name: "未知小站 (测试源)",
    accessType: "HTML",
    capabilities: ["search", "chapter", "auth"],
    enabled: true,
    official: false,
    author: "Yunwei",
    tags: ["小说"],
    version: "0.8.0",
    health: { pingStatus: "unreachable", pingLatencyMs: 890 },
  },
  {
    pluginId: "qidian_com_app",
    name: "起点中文网 (App)",
    accessType: "JSON",
    capabilities: ["search", "detail", "toc", "chapter", "auth"],
    enabled: true,
    official: true,
    author: "Yunwei",
    tags: ["小说"],
    version: "1.0.0",
    health: { pingStatus: "reachable", pingLatencyMs: 36 },
  },
  {
    pluginId: "qidian_com_web",
    name: "起点中文网 (Web)",
    accessType: "HTTP",
    capabilities: ["search", "detail", "toc", "chapter", "auth"],
    enabled: true,
    official: true,
    author: "Yunwei",
    tags: ["小说"],
    version: "1.0.0",
    health: { pingStatus: "reachable", pingLatencyMs: 48 },
  },
]

function run(command, args, cwd, options = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: { ...process.env, DISABLE_HMR: "true", BROWSER: "none", ...options.env },
      stdio: options.stdio ?? "pipe",
      shell: useShell,
    })
    let output = ""
    child.stdout?.on("data", (data) => {
      output += data.toString()
      options.onOutput?.(data.toString())
    })
    child.stderr?.on("data", (data) => {
      output += data.toString()
      options.onOutput?.(data.toString())
    })
    child.on("error", reject)
    child.on("close", (code) => {
      if (code === 0) resolvePromise(output)
      else reject(new Error(`${command} ${args.join(" ")} failed with ${code}\n${output}`))
    })
  })
}

async function ensureDeps(projectDir) {
  const viteBin = join(projectDir, "node_modules", ".bin", process.platform === "win32" ? "vite.cmd" : "vite")
  if (existsSync(viteBin)) return
  console.log(`[deps] ${projectDir} 缺少 node_modules，执行 npm ci --no-audit --no-fund`)
  await run(npmCmd, ["ci", "--no-audit", "--no-fund"], projectDir, { stdio: "inherit" })
}

function reserveAvailablePort(preferredPort) {
  return new Promise((resolvePromise, reject) => {
    const server = createServer()
    server.unref()
    server.once("error", reject)
    server.listen({ host: "127.0.0.1", port: preferredPort, exclusive: true }, () => {
      const address = server.address()
      const port = typeof address === "object" && address ? address.port : preferredPort
      server.close((error) => error ? reject(error) : resolvePromise(port))
    })
  })
}

async function findAvailablePort(preferredPort) {
  try {
    return await reserveAvailablePort(preferredPort)
  } catch (error) {
    if (error?.code !== "EADDRINUSE") throw error
    return reserveAvailablePort(0)
  }
}

function startVite(projectDir, port) {
  const viteEntry = join(projectDir, "node_modules", "vite", "bin", "vite.js")
  const child = spawn(process.execPath, [viteEntry, "--host", "127.0.0.1", "--port", String(port)], {
    cwd: projectDir,
    env: { ...process.env, DISABLE_HMR: "true", BROWSER: "none" },
    stdio: "pipe",
    shell: false,
  })
  child.stdout.on("data", (data) => process.stdout.write(`[vite:${port}] ${data}`))
  child.stderr.on("data", (data) => process.stderr.write(`[vite:${port}] ${data}`))
  return child
}

async function waitFor(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url)
      if (res.ok) return
      lastError = new Error(`HTTP ${res.status}`)
    } catch (error) {
      lastError = error
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 500))
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message || "unknown error"}`)
}

async function installMocks(page, scenario = {}) {
  await page.route("https://covers.example/sanguo.svg", route => route.fulfill({contentType: "image/svg+xml", body: decodeURIComponent(coverFixture("三国演义", "#40564c", "#e4d0a5").split(",").slice(1).join(","))}))
  await page.route("**/api/**", async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    const method = req.method()
    const json = mockApi(path, method, scenario)
    await route.fulfill({
      status: typeof json.status === "number" ? json.status : 200,
      contentType: "application/json",
      body: JSON.stringify(json.body ?? json),
    })
  })
}

function mockApi(path, method, scenario = {}) {
  if (path === "/api/direct/sources") return {items: [{id: "quanben5_com", name: "全本小说网", default: true}, {id: "hjwzw_com", name: "黄金屋", default: true}]}
  if (path === "/api/direct/downloads" || path === "/api/accounts/invitations") return {items: []}
  if (path === "/api/direct/shelf" && scenario.library === "empty") return {items: []}
  if (path === "/api/direct/shelf") return {items: [{bookId: "fixture-book", sourceId: "fixture", sourceName: "全本小说网", name: "三国演义", author: "罗贯中", coverUrl: "https://covers.example/sanguo.svg", sourceCount: 3}]}
  if (path.endsWith("/fixture-book/progress")) return {chapterIndex: 0, position: 0, revision: 0}
  if (path.endsWith("/fixture-book/detail")) return {bookId: "fixture-book", sourceId: "fixture", sourceName: "全本小说网", name: "三国演义", author: "罗贯中", coverUrl: "https://covers.example/sanguo.svg", sourceCount: 3}
  if (path.endsWith("/fixture-book/toc")) return {chapters: [{index: 0, title: "第一回 宴桃园豪杰三结义"}, {index: 1, title: "第二回"}]}
  if (path.endsWith("/fixture-book/chapters/0")) return {title: "第一回 宴桃园豪杰三结义", content: ("滚滚长江东逝水，浪花淘尽英雄。是非成败转头空。\n青山依旧在，几度夕阳红。\n\n").repeat(12)}
  if (path === "/api/auth/entrypoint") {
    return { entrypoint: scenario.entrypoint || (scenario.role === "admin" ? "admin" : "public"), authMode: scenario.entrypoint === "combined" ? "account_invite" : "legacy" }
  }
  if (path === "/api/auth/me") {
    if (scenario.role === "anonymous") return { status: 401, body: { detail: "未登录" } }
    const role = scenario.role || "admin"
    return { user: { userId: role, username: role === "admin" ? "管理员" : "阅读用户", role } }
  }
  if (path === "/api/auth/login") {
    if (scenario.loginError) return { status: 401, body: { detail: "用户名或密码错误" } }
    return { user: { userId: "admin", username: "管理员", role: "admin" } }
  }
  if (path === "/api/auth/access/redeem") {
    return { token: "visual-session", user: { userId: "user", username: "阅读用户", role: "user" } }
  }
  if (path === "/api/auth/logout") return { ok: true }
  if (path === "/api/auth/bootstrap") return { status: 404, body: { detail: "Not Found" } }
  if (path === "/api/console/status") {
    return {
      health: "degraded",
      uptimeSeconds: 1220400,
      version: "1.2.0-beta",
      pluginStats: { total: 342, enabled: 310, disabled: 32, healthy: 298, unhealthy: 12, checked: 310, unknown: 0 },
    }
  }
  if (path === "/api/console/plugins") {
    const items = scenario.plugins === "empty" ? [] : plugins
    return { items, total: items.length }
  }
  if (path === "/api/console/plugins/ping") {
    return { results: plugins.map((plugin) => ({ pluginId: plugin.pluginId, status: plugin.health.pingStatus, latencyMs: plugin.health.pingLatencyMs })) }
  }
  if (path.endsWith("/attempts")) return { attempts: [] }
  if (path.endsWith("/ping")) {
    const pluginId = path.split("/").at(-2)
    return { pluginId, status: "reachable", latencyMs: 32 }
  }
  if (path === "/api/console/plugins/reload" || path.includes("/enable") || path.includes("/batch-")) {
    return { ok: true }
  }
  if (path.startsWith("/api/console/plugins/")) {
    return {
      ...plugins[0],
      domains: ["m.qidian.com"],
      baseUrls: ["https://m.qidian.com"],
      lastModified: "2026-07-16T08:00:00+08:00",
      auth: { mode: "required", loginUrl: "https://passport.qidian.com", cookieDomains: ["qidian.com"] },
      content: { access: "authenticated" },
      browser: { mode: "none" },
    }
  }
  if (path === "/api/console/search-jobs" && method === "POST") {
    return searchJob()
  }
  if (path === "/api/console/search-jobs" || path === "/api/console/search-jobs/") {
    return { items: [searchJob()], total: 1 }
  }
  if (path.includes("/api/console/search-jobs/job-1/events")) {
    return { events: searchEvents() }
  }
  if (path.includes("/api/console/search-jobs/job-1")) return searchJob()
  if (path === "/api/console/official-sources") {
    if (scenario.officialSources === "error") return { status: 500, body: { detail: "上游状态查询失败" } }
    if (scenario.officialSources === "empty") return { items: [], total: 0 }
    const items = officialSources()
    return { items, total: items.length }
  }
  if (path.includes("/api/console/official-sources/") && path.endsWith("/login-capabilities")) {
    return {
      pluginId: "qidian_com_web",
      methods: ["phone", "cookie", "browser"],
      defaultMethod: "phone",
      privateFeatures: { phoneAuth: true, cookieAuth: true, reviews: true },
      hasPrivatePackage: true,
    }
  }
  if (path.includes("/auth/check")) return { authenticated: true, accountName: "138****0000" }
  if (path === "/api/console/settings") return settings()
  if (path === "/api/console/aggregate-settings") return aggregateSettings()
  if (path === "/api/console/lexicon/status") {
    return { commitSha: "a1b2c3d4ef", fileCount: 45, wordCount: 12400, updatedAt: "2026-07-08T10:00:00+08:00" }
  }
  if (path === "/api/console/lexicon/update") return { ok: true }
  if (path === "/api/console/users" && method === "GET") {
    return {
      items: [
        { userId: "admin", username: "管理员", role: "admin", disabled: false, createdAt: "2026-07-01T08:30:00+08:00", updatedAt: "2026-07-16T08:30:00+08:00" },
        { userId: "reader-1", username: "阅读用户", role: "user", disabled: false, createdAt: "2026-07-03T10:20:00+08:00", updatedAt: "2026-07-15T21:10:00+08:00" },
        { userId: "reader-2", username: "暂停账户", role: "user", disabled: true, createdAt: "2026-07-05T14:00:00+08:00", updatedAt: "2026-07-12T09:15:00+08:00" },
      ],
      total: 3,
    }
  }
  if (path === "/api/subscribe/search") return subscribeJob()
  if (path === "/api/subscribe/search/job-sub-1") return subscribeJob()
  if (path === "/api/subscribe/library" || path === "/api/subscribe/library/mine") {
    const items = scenario.library === "empty" ? [] : books
    return { items, total: items.length }
  }
  if (path === "/api/console/library-books") {
    const items = scenario.library === "empty" ? [] : books
    return { items, total: items.length }
  }
  if (path === "/api/subscribe/books/book-2") return bookSummary(books[1])
  if (path.includes("/api/subscribe/books/book-2/chapters")) return { items: chapters(), total: 50 }
  if (path.includes("/api/subscribe/chapters/")) {
    return {
      title: "第1章 诡异天道",
      content:
        "这里是试读的预览内容。文字排版模仿真实的阅读体验。\n“你醒了？”一个沙哑的声音从角落里传来。\n李火旺转过头，看到一个身披破烂道袍的老者正盘腿坐在蒲团上。",
    }
  }
  if (path === "/api/console/library-books/book-2") return bookSummary(books[1])
  if (path.includes("/api/console/library-books/book-2/summary")) return bookSummary(books[1])
  if (path.includes("/api/console/library-books/book-2/chapters/") && path.endsWith("/progress")) {
    return chapterProgress()
  }
  if (path.includes("/api/console/library-books/book-2/chapters")) return { items: chapters(), total: 50 }
  if (path.includes("/api/console/library-books/book-2/logs")) return { items: [], total: 0 }
  if (path.includes("/api/console/chapter/")) {
    return {
      title: "第1章 诡异天道",
      content:
        "这里是试读的预览内容。文字排版模仿真实的阅读体验。\n“你醒了？”一个沙哑的声音从角落里传来。\n李火旺转过头，看到一个身披破烂道袍的老者正盘腿坐在蒲团上。",
    }
  }
  return { status: 404, body: { detail: `visual-diff mock missing: ${method} ${path}` } }
}

function subscribeJob() {
  return {
    jobId: "job-sub-1",
    status: "completed",
    cards: searchCards,
    events: searchEvents(),
  }
}

function searchJob() {
  return {
    jobId: "job-1",
    status: "completed",
    sourceCount: 124,
    completedCount: 124,
    successCount: 89,
    errorCount: 35,
    resultCount: 12,
    result: {
      items: [
        { name: "深海余烬", author: "远瞳", sourceCount: 18, score: 98, sourceId: "com.qidian" },
        { name: "深海", author: "未知", sourceCount: 3, score: 45, sourceId: "net.biquge" },
      ],
    },
  }
}

function searchEvents() {
  return [
    { type: "summary", sourceCount: 124 },
    { type: "source_complete", sourceId: "com.qidian", sourceName: "com.qidian", status: "success", latencyMs: 120, count: 18 },
    { type: "source_complete", sourceId: "net.biquge", sourceName: "net.biquge", status: "success", latencyMs: 840, count: 3 },
    { type: "source_complete", sourceId: "org.tadu", sourceName: "org.tadu", status: "timeout", latencyMs: 5000, count: 0 },
    { type: "source_complete", sourceId: "com.zongheng", sourceName: "com.zongheng", status: "error", latencyMs: 45, error: "HTTP 500", count: 0 },
  ]
}

function bookSummary(book) {
  return {
    found: true,
    ...book,
    book,
    addedByUsername: "System",
    startChapterIndex: 1,
    totalChaptersAtSubscribe: book.totalChapters,
    currentPolicyVersion: 2,
    autoArchiveOnComplete: true,
    subscription: {
      status: "active",
      startChapterIndex: 20,
      autoArchiveOnComplete: false,
    },
    personalProgress: {
      rangeStartIndex: 20,
      rangeEndIndex: 1100,
      fullCount: 430,
      previewCount: 110,
      failedCount: 50,
      pendingCount: 491,
      continuousReadableThroughIndex: 559,
      coverageRatio: 0.4995,
    },
    searchVisibilityStatus: "visible",
    lastCheckedAt: "2026-07-08T14:30:00+08:00",
    nextCheckTime: "2026-07-08T20:30:00+08:00",
    freeChapterEndIndex: 532,
    bookState: {
      readableChapterCount: 540,
      previewChapterCount: 150,
      failedChapterCount: 50,
    },
    sourceMapRefresh: { completed: true, lastVerifiedAt: "2026-07-08T12:30:00+08:00" },
    sourceMapSummary: [
      { sourceId: "biquge", sourceName: "笔趣阁", score: 98, chapterCount: 1100, lastChapter: "第1100章", bookStatus: "正常" },
      { sourceId: "shuqige", sourceName: "书趣阁", score: 85, chapterCount: 1089, lastChapter: "第1089章", bookStatus: "延迟" },
      { sourceId: "piaotian", sourceName: "飘天文学", score: 80, chapterCount: 1050, lastChapter: "第1050章", bookStatus: "延迟" },
      { sourceId: "dingdian", sourceName: "顶点小说", score: 75, chapterCount: 1010, lastChapter: "第1010章", bookStatus: "离线" },
      { sourceId: "miaobige", sourceName: "妙笔阁", score: 72, chapterCount: 980, lastChapter: "第980章", bookStatus: "正常" },
    ],
  }
}

function chapters() {
  return Array.from({ length: 50 }, (_, index) => {
    const chapterIndex = index + 1
    let status = "readable"
    let isVip = false
    let previewOnly = false
    if (index > 45) {
      status = "pending"
      isVip = true
    } else if (index > 40) {
      status = "failed"
      isVip = true
    } else if (index > 35) {
      status = "preview"
      isVip = true
      previewOnly = true
    } else if (index > 20) {
      isVip = true
    }
    return {
      chapterId: `chapter-${chapterIndex}`,
      readChapterId: `legadohub_ai_aggregate:chapter-${chapterIndex}`,
      chapterIndex,
      title: `第${chapterIndex}章 诡异天道`,
      status,
      isVip,
      previewOnly,
      sourceId: index % 3 === 0 ? "备用源" : "主源",
      sourceWordCount: 3200,
      contentLength: 3200,
      hasContent: status !== "pending" && status !== "failed",
      error: status === "failed" ? "超时" : "",
    }
  })
}

function chapterProgress() {
  return {
    found: true,
    bookId: "book-2",
    chapterId: "chapter-1",
    chapterIndex: 1,
    title: "第1章 诡异天道",
    status: "processed",
    previewOnly: false,
    contentLength: 3276,
    sourceWordCount: 3200,
    traceSummary: {
      currentStep: "正文已入库",
      nextStep: "等待下一次调度",
      selectedSource: "起点中文网",
      selectedContentSource: "起点中文网 App",
      fallbackSourceId: "",
      alignmentPassed: true,
      alignmentReason: "标题与预览内容一致",
      titleSimilarity: 0.998,
      previewSimilarity: 0.986,
      processedAt: "2026-07-16T08:30:00+08:00",
      traceHash: "trace-a1b2c3d4",
      stage3Verdict: "trusted_current",
      stage3Reason: "内容完整且章节顺序正确",
      currentChapterIndex: 1,
      currentChapterTitle: "第1章 诡异天道",
      nextChapterIndex: 2,
      nextChapterTitle: "第2章 坐忘道",
    },
  }
}

function officialSources() {
  return [
    {
      pluginId: "qidian_com_app",
      name: "起点中文网 (App)",
      author: "Yunwei",
      version: "1.0.0",
      enabled: true,
      auth: { mode: "required" },
      authStatus: {
        authenticated: true,
        hasCookies: true,
        accountName: "138****0000",
        lastCheckedAt: "2026-07-16 08:30",
      },
    },
    {
      pluginId: "qidian_com_web",
      name: "起点中文网 (Web)",
      author: "Yunwei",
      version: "1.0.0",
      enabled: true,
      auth: { mode: "required" },
      authStatus: {
        authenticated: false,
        hasCookies: false,
        accountName: "",
        lastCheckedAt: "2026-07-16 08:28",
      },
    },
  ]
}

function settings() {
  return {
    sourcePool: {
      max_concurrency: 64,
      source_timeout_seconds: 5,
      browser_search_timeout_seconds: 15,
      default_user_agent: "Mozilla/5.0...",
      officialSourceInNormalSearch: true,
      proxy: { url: "http://127.0.0.1:7890" },
    },
    searchScoreFilter: 40,
    contentWorkflow: { aggregationMode: "balanced", purifyMode: "conservative" },
  }
}

function aggregateSettings() {
  return {
    contentWorkflow: {
      sourceCandidateLimit: 5,
      aggregateCheckIntervalMinutes: 60,
      primarySourcePriority: ["qidian_com_app", "qidian_com_web"],
      candidateSourcePriority: ["com.biquge.general", "com.tadu", "net.wenku8"],
    },
  }
}

async function assertMobileHorizontalScroll(page, testId) {
  const viewport = page.viewportSize()
  if (!viewport || viewport.width > 500) return

  const state = await page.getByTestId(testId).evaluate((boundary) => {
    const candidates = [boundary, ...boundary.querySelectorAll("*")]
    const container = candidates.find((element) => {
      const overflowX = window.getComputedStyle(element).overflowX
      return ["auto", "scroll"].includes(overflowX) && element.scrollWidth > element.clientWidth
    })
    const boundaryRect = boundary.getBoundingClientRect()
    if (!container) {
      return {
        found: false,
        boundaryWidth: boundaryRect.width,
        viewportWidth: window.innerWidth,
      }
    }
    container.scrollLeft = container.scrollWidth
    const reachableScrollLeft = container.scrollLeft
    container.scrollLeft = 0
    return {
      found: true,
      boundaryWidth: boundaryRect.width,
      viewportWidth: window.innerWidth,
      overflowX: window.getComputedStyle(container).overflowX,
      clientWidth: container.clientWidth,
      scrollWidth: container.scrollWidth,
      reachableScrollLeft,
    }
  })
  if (!state.found || state.boundaryWidth > state.viewportWidth + 1 || !state.reachableScrollLeft || state.reachableScrollLeft <= 0) {
    throw new Error(`${testId} is not horizontally scrollable on mobile: ${JSON.stringify(state)}`)
  }
}

async function capture(browser, url, viewport, scenario, prepare, preserveScroll = false) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    colorScheme: "light",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  })
  try {
    const page = await context.newPage()
    await installMocks(page, scenario)
    page.on("pageerror", (error) => console.warn(`[pageerror] ${url}: ${error.message}`))
    page.on("console", (msg) => {
      if (msg.type() === "error") console.warn(`[console] ${url}: ${msg.text()}`)
    })
    await page.addInitScript(() => {
      window.EventSource = class {
        constructor(url) {
          this.closed = false
          setTimeout(() => { if (!this.closed) this.onopen?.({}) }, 0)
          if (typeof url === "string" && url.includes("book-2/logs")) {
            const messages = [
              { ts: "2023-10-27T14:30:00", event: "Checking for updates..." },
              { ts: "2023-10-27T14:30:01", event: "No new chapters found." },
              { ts: "2023-10-27T14:32:11", event: "Chapter 541 processing failed: rate limit exceeded.", errorCode: "RATE_LIMIT" },
            ]
            messages.forEach((msg, i) => {
              setTimeout(() => { if (!this.closed) this.onmessage?.({ data: JSON.stringify(msg) }) }, 50 + i * 50)
            })
          }
        }
        close() { this.closed = true }
      }
    })
    await page.goto(url, { waitUntil: "networkidle" })
    await page.addStyleTag({
      content: `
        *, *::before, *::after {
          animation-duration: 0s !important;
          animation-delay: 0s !important;
          transition-duration: 0s !important;
          caret-color: transparent !important;
        }
        html { scroll-behavior: auto !important; }
      `,
    })
    if (prepare) await prepare(page)
    await page.waitForLoadState("networkidle").catch(() => {})
    await page.waitForTimeout(250)
    if (!preserveScroll) await page.evaluate(() => window.scrollTo(0, 0))
    const screenshot = await page.screenshot({ fullPage: false, animations: "disabled" })
    if (viewport.name === "desktop") {
      const sidebar = await page.evaluate(async () => {
        const aside = document.querySelector("aside")
        if (!aside) return null
        const originalScrollY = window.scrollY
        const maxScrollY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight)
        window.scrollTo(0, Math.min(400, maxScrollY))
        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
        const rect = aside.getBoundingClientRect()
        const state = {
          position: getComputedStyle(aside).position,
          top: rect.top,
          height: rect.height,
          viewportHeight: window.innerHeight,
          maxScrollY,
        }
        window.scrollTo(0, originalScrollY)
        return state
      })
      if (sidebar && (
        Math.abs(sidebar.height - sidebar.viewportHeight) > 1
        || (sidebar.maxScrollY > 0 && (
          sidebar.position !== "sticky"
          || Math.abs(sidebar.top) > 1
        ))
      )) {
        throw new Error(`desktop sidebar is not viewport-independent: ${JSON.stringify(sidebar)}`)
      }
    }
    return screenshot
  } finally {
    await context.close().catch(() => {})
  }
}

async function compareImages(browser, expected, actual, threshold = 16) {
  const page = await browser.newPage({ viewport: { width: 64, height: 64 } })
  try {
    const result = await page.evaluate(
      async ({ expectedBase64, actualBase64, thresholdValue }) => {
      const load = (src) =>
        new Promise((resolvePromise, reject) => {
          const img = new Image()
          img.onload = () => resolvePromise(img)
          img.onerror = reject
          img.src = src
        })
      const expectedImg = await load(`data:image/png;base64,${expectedBase64}`)
      const actualImg = await load(`data:image/png;base64,${actualBase64}`)
      const width = Math.max(expectedImg.width, actualImg.width)
      const height = Math.max(expectedImg.height, actualImg.height)
      const canvas = document.createElement("canvas")
      const ctx = canvas.getContext("2d")
      canvas.width = width
      canvas.height = height
      ctx.fillStyle = "#fff"
      ctx.fillRect(0, 0, width, height)
      ctx.drawImage(expectedImg, 0, 0)
      const expectedData = ctx.getImageData(0, 0, width, height).data
      ctx.fillStyle = "#fff"
      ctx.fillRect(0, 0, width, height)
      ctx.drawImage(actualImg, 0, 0)
      const actualData = ctx.getImageData(0, 0, width, height).data
      const diffCanvas = document.createElement("canvas")
      const diffCtx = diffCanvas.getContext("2d")
      diffCanvas.width = width
      diffCanvas.height = height
      const diff = diffCtx.createImageData(width, height)
      let mismatch = 0
      for (let i = 0; i < expectedData.length; i += 4) {
        const delta =
          Math.abs(expectedData[i] - actualData[i]) +
          Math.abs(expectedData[i + 1] - actualData[i + 1]) +
          Math.abs(expectedData[i + 2] - actualData[i + 2]) +
          Math.abs(expectedData[i + 3] - actualData[i + 3])
        const out = i
        if (delta > thresholdValue) {
          mismatch += 1
          diff.data[out] = 239
          diff.data[out + 1] = 68
          diff.data[out + 2] = 68
          diff.data[out + 3] = 255
        } else {
          const gray = Math.round((actualData[i] + actualData[i + 1] + actualData[i + 2]) / 3)
          diff.data[out] = gray
          diff.data[out + 1] = gray
          diff.data[out + 2] = gray
          diff.data[out + 3] = 60
        }
      }
      diffCtx.putImageData(diff, 0, 0)
      return {
        width,
        height,
        mismatch,
        ratio: mismatch / (width * height),
        diffBase64: diffCanvas.toDataURL("image/png").split(",")[1],
      }
      },
      {
        expectedBase64: expected.toString("base64"),
        actualBase64: actual.toString("base64"),
        thresholdValue: threshold,
      },
    )
    return { ...result, diff: Buffer.from(result.diffBase64, "base64") }
  } finally {
    await page.close().catch(() => {})
  }
}

async function main() {
  await mkdir(outputDir, { recursive: true })
  await ensureDeps(frontendDir)
  if (updateBaseline) await mkdir(baselineDir, { recursive: true })
  ports.current = await findAvailablePort(ports.current)

  const currentServer = startVite(frontendDir, ports.current)
  const servers = [currentServer]
  const stopServers = () => servers.forEach((child) => child.kill())
  process.on("exit", stopServers)
  process.on("SIGINT", () => {
    stopServers()
    process.exit(130)
  })

  try {
    await waitFor(`http://127.0.0.1:${ports.current}/console`)

    const browser = await chromium.launch()
    const records = []
    try {
      for (const viewport of viewports) {
        for (const pageDef of pages) {
          if (pageDef.viewports && !pageDef.viewports.includes(viewport.name)) continue
          const prefix = `${viewport.name}-${pageDef.id}`
          const currentUrl = `http://127.0.0.1:${ports.current}${pageDef.currentPath}`
          console.log(`[capture] ${prefix}`)
          const currentShot = await capture(browser, currentUrl, viewport, pageDef.scenario, pageDef.prepare, pageDef.preserveScroll)
          const baselinePath = join(baselineDir, `${prefix}.png`)
          if (updateBaseline) await writeFile(baselinePath, currentShot)
          if (!existsSync(baselinePath)) {
            throw new Error(`Missing baseline: ${baselinePath}. Run with --update-baseline after review.`)
          }
          const baselineShot = await readFile(baselinePath)
          const comparison = await compareImages(browser, baselineShot, currentShot)
          await writeFile(join(outputDir, `${prefix}-baseline.png`), baselineShot)
          await writeFile(join(outputDir, `${prefix}-current.png`), currentShot)
          await writeFile(join(outputDir, `${prefix}-diff.png`), comparison.diff)
          records.push({
            viewport: viewport.name,
            page: pageDef.id,
            title: pageDef.title,
            currentPath: pageDef.currentPath,
            scenario: pageDef.scenario,
            mismatchPixels: comparison.mismatch,
            mismatchRatio: Number(comparison.ratio.toFixed(6)),
            similarity: Number((1 - comparison.ratio).toFixed(6)),
            passed: 1 - comparison.ratio >= minimumSimilarity,
            width: comparison.width,
            height: comparison.height,
            files: {
              baseline: `${prefix}-baseline.png`,
              current: `${prefix}-current.png`,
              diff: `${prefix}-diff.png`,
            },
          })
        }
      }
    } finally {
      await browser.close()
    }

    const mismatchPixels = records.reduce((total, item) => total + item.mismatchPixels, 0)
    const comparedPixels = records.reduce((total, item) => total + item.width * item.height, 0)
    const overallMismatchRatio = comparedPixels ? mismatchPixels / comparedPixels : 1
    const overallSimilarity = 1 - overallMismatchRatio
    const failedRecords = records.filter((item) => !item.passed).map((item) => `${item.viewport}:${item.page}`)
    const report = {
      generatedAt: new Date().toISOString(),
      mode: updateBaseline ? "update-baseline" : "compare",
      outputDir,
      baselineDir,
      currentBaseUrl: `http://127.0.0.1:${ports.current}`,
      threshold: 16,
      minimumSimilarity,
      mismatchPixels,
      comparedPixels,
      overallMismatchRatio: Number(overallMismatchRatio.toFixed(6)),
      overallSimilarity: Number(overallSimilarity.toFixed(6)),
      failedRecords,
      gateEvaluated: !updateBaseline,
      passed: updateBaseline ? null : overallSimilarity >= minimumSimilarity && failedRecords.length === 0,
      note: updateBaseline
        ? "Baseline files were updated. This mode is not a release gate; run compare mode after review."
        : "Baseline comes from approved real Console routes and states. The legacy untitled prototype is historical reference only.",
      records,
    }
    await writeFile(join(outputDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`)
    await writeFile(join(outputDir, "report.md"), renderMarkdown(report))
    console.log(`\n[done] report: ${join(outputDir, "report.md")}`)
    if (updateBaseline) {
      console.log("[baseline] update completed; run again without --update-baseline to evaluate the gate")
    } else if (!report.passed) {
      throw new Error(`Visual regression gate failed: overall ${(overallSimilarity * 100).toFixed(2)}%, scenarios ${failedRecords.join(", ") || "none"}`)
    }
  } finally {
    stopServers()
  }
}

function renderMarkdown(report) {
  const lines = [
    "# Console Visual Diff Report",
    "",
    `Generated: ${report.generatedAt}`,
    `Mode: ${report.mode}`,
    `Overall similarity: ${(report.overallSimilarity * 100).toFixed(2)}%`,
    `Required similarity: ${(report.minimumSimilarity * 100).toFixed(0)}%`,
    `Result: ${report.gateEvaluated ? (report.passed ? "PASS" : "FAIL") : "NOT EVALUATED"}`,
    "",
    report.note,
    "",
    "| Viewport | Page | Similarity | Mismatch | Files |",
    "| --- | --- | ---: | ---: | --- |",
  ]
  for (const item of report.records) {
    const pct = `${(item.mismatchRatio * 100).toFixed(2)}%`
    lines.push(
      `| ${item.viewport} | ${item.title} | ${(item.similarity * 100).toFixed(2)}% | ${pct} | [baseline](${item.files.baseline}) / [current](${item.files.current}) / [diff](${item.files.diff}) |`,
    )
  }
  lines.push("")
  lines.push("## How To Re-run")
  lines.push("")
  lines.push("```powershell")
  lines.push("cd C:\\Home\\Workspace\\UGit\\legado-hub\\frontend")
  lines.push("node .\\visual-diff\\run-visual-diff.mjs")
  lines.push("```")
  lines.push("")
  lines.push("## Update Approved Baseline")
  lines.push("")
  lines.push("```powershell")
  lines.push("node .\\visual-diff\\run-visual-diff.mjs --update-baseline")
  lines.push("```")
  lines.push("")
  return `${lines.join("\n")}\n`
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
