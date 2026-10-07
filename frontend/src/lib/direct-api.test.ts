import { afterEach, describe, expect, it, vi } from "vitest"
import { streamSearch } from "./direct-api"

afterEach(() => vi.unstubAllGlobals())
describe("streamSearch", () => {
  it("decodes split UTF-8 frames and publishes each source before completion", async () => {
    const wire = new TextEncoder().encode('data: {"sourceId":"中文","items":[],"latencyMs":10}\n\nevent: done\ndata: {}\n\n')
    const stream = new ReadableStream({ start(c) { for (let i = 0; i < wire.length; i += 3) c.enqueue(wire.slice(i, i + 3)); c.close() } })
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream, { status: 200 })))
    const receive = vi.fn()
    await streamSearch("书", ["src"], 1, new AbortController().signal, receive)
    expect(receive).toHaveBeenCalledTimes(1)
    expect(receive.mock.calls[0][0].sourceId).toBe("中文")
  })
  it("surfaces server errors instead of leaving a spinner", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"请选择书源"}', { status: 400 })))
    await expect(streamSearch("书", [], 1, new AbortController().signal, vi.fn())).rejects.toThrow("请选择书源")
  })
})

import { directRequest } from "./direct-api"
it("shows the structured site removal reason returned by the global error handler", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({detail: {message: "轻小说文库：原站因版权问题已停止提供本书阅读", code: "HTTP_410"}}), {status: 410})))
  await expect(directRequest("/books/test/chapters/0")).rejects.toThrow("原站因版权问题")
})
it("keeps a status fallback for a gateway error without JSON", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad Gateway", {status: 502})))
  await expect(directRequest("/books/test/chapters/0")).rejects.toThrow("请求失败 (502)")
})
