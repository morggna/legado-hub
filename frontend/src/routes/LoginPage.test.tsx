import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter, Route, Routes } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { LoginPage } from "./LoginPage"

const authMocks = vi.hoisted(() => ({
  login: vi.fn(),
  loginWithAccessCode: vi.fn(),
  entrypoint: "public" as "public" | "admin" | "combined",
}))

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: null,
    entrypoint: authMocks.entrypoint,
    isLoading: false,
    login: authMocks.login,
    loginWithAccessCode: authMocks.loginWithAccessCode,
  }),
}))

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>控制台</div>} />
      </Routes>
    </MemoryRouter></QueryClientProvider>,
  )
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authMocks.login.mockResolvedValue(undefined)
    authMocks.loginWithAccessCode.mockResolvedValue(undefined)
    authMocks.entrypoint = "public"
  })

  it("uses the personal access code flow by default", async () => {
    const user = userEvent.setup()
    renderPage()

    expect(screen.getByLabelText("授权码 / 订阅链接", { selector: "input" })).toBeInTheDocument()
    expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "管理员" })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText("授权码 / 订阅链接", { selector: "input" }), "LH1.reader.secret")
    await user.click(screen.getByRole("button", { name: "登录" }))

    await waitFor(() => expect(authMocks.loginWithAccessCode).toHaveBeenCalledWith("LH1.reader.secret"))
    expect(await screen.findByText("控制台")).toBeInTheDocument()
  })

  it("shows only administrator password login on the admin entrypoint", async () => {
    authMocks.entrypoint = "admin"
    const user = userEvent.setup()
    renderPage()

    expect(screen.queryByLabelText("授权码 / 订阅链接", { selector: "input" })).not.toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "管理员" })).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText("用户名"))
    await user.type(screen.getByLabelText("用户名"), "operator")
    await user.type(screen.getByLabelText("密码"), "password-123")
    await user.click(screen.getByRole("button", { name: "登录" }))

    await waitFor(() => expect(authMocks.login).toHaveBeenCalledWith("operator", "password-123"))
    expect(await screen.findByText("控制台")).toBeInTheDocument()
  })
})

describe("combined login", () => {
  it("offers password login to normal users on the same entrance", async () => {
    authMocks.entrypoint = "combined"
    const user = userEvent.setup()
    renderPage()
    expect(screen.queryByLabelText("授权码 / 订阅链接")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "有邀请码？注册账号" })).toBeInTheDocument()
    await user.clear(screen.getByLabelText("用户名"))
    await user.type(screen.getByLabelText("用户名"), "reader")
    await user.type(screen.getByLabelText("密码"), "reader-password")
    await user.click(screen.getByRole("button", { name: "登录" }))
    await waitFor(() => expect(authMocks.login).toHaveBeenCalledWith("reader", "reader-password"))
  })
})
