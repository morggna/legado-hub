# Unified personal reading fork

The combined FastAPI application serves account login, personal reading and admin
management from one listener. Deployment uses account_invite mode: passwords for
login and an administrator-issued invitation only for registration. Legacy access
code routes are not registered in this mode. Dedicated upstream listeners remain
available only as explicit legacy compatibility configurations.

All /api/direct endpoints authenticate the session. The user ID always comes from
the server session. Only enabled, anonymous, free plugins supporting search/detail/
toc/chapter are eligible. Search initially selects all eligible sources and streams
results per source; errors remain visible. URLs must match the plugin's declared
domains and cannot use IP literals, credentials or arbitrary ports. The existing
PluginScheduler owns networking, timeout and source concurrency policies.

Adding a book stores server-resolved metadata in a personal shelf. Reading loads
one chapter at a time, without creating subscription or download jobs. Detail and
TOC caches have a five-minute TTL, 128-entry limit and shared in-flight requests.
Direct requests use eight total slots and four slots per search; each user may
have two concurrent searches. Progress writes serialize optimistic revisions;
stale writes return 409 instead of overwriting another device's progress.

Full-book download is a separate explicit action. Two workers consume a persistent
queue, limited to two pending/running jobs per user and twenty globally. Pause
awaits task cancellation; resume reuses completed chapter files. Each job uses a
validated TOC snapshot. Downloads are limited to 20,000 chapters, 2 MB per chapter
and 256 MB per book. Private cache directories use hashes of user and book IDs.
A personal shelf entry is required to access cached content or the TXT export.

Schema 16 adds direct_bookshelf, direct_progress, direct_download_jobs and
registration_invites. Invitations are hashed, bounded by expiry/use count, and
consumed atomically with account creation. Password reset revokes sessions.

The reader adapts legado-server's GPL-3.0 typography, settings, CSS, icons and
pagination/gesture helpers. It opens in immersive mode. Preferences are stored
under a per-user browser key; progress remains server-side. See
frontend/third-party/legado-server.md and the complete bundled license. Unsupported
TTS, source switching and offline PWA controls are not presented as available.

Deployment pins the upstream v0.4.4 image digest, overlays this fork and uses clean
persistent directories. The only published listener is 127.0.0.1:8765. The reverse
proxy is operator-managed; book.uclau.de is allowed. No old accounts, books, cookies
or progress are copied. Existing retired services remain stopped.

## Scope limitation

Sources use upstream Python plugins managed by administrators. Per-user import
and execution of Legado JSON rules is not implemented. Shared plugins must not be
represented as private sources. External-source availability depends on each site.

## Verification

Use verify.ps1 before release. Backend tests cover auth, invitation consumption,
user isolation, stale writes, URL boundaries, cancellation, chapter-only fetch,
explicit downloads and recovery. Frontend checks include lint/build/tests and
reviewed desktop/mobile visual comparisons. Network-independent storage fixtures
stub live discovery; separate container acceptance exercises real sources.

The default Docker test asset 本地测试 was absent from Termark inventory. Acceptance
therefore uses an isolated SG-Oracle container with separate runtime volumes and
no existing service data. Production startup follows container acceptance.


## On-demand multi-source aggregation (2026-10-07)

- `/api/direct/search` retains per-source SSE diagnostics and emits cumulative `groups` using upstream search grouping/ranking. One book is identified by normalized title + author, independent of the set of responding sources. Ambiguous unknown authors are kept separate from known homonyms.
- `POST /api/direct/shelf` accepts only source-qualified book IDs. The server resolves source metadata, verifies common identity, merges candidates, and stores a single personal shelf entry including cover URL. Adding performs no TOC or chapter crawl.
- The original TOC candidate ranking, sentence-order outlier detection, similarity voting and gap-based selection now live in `aggregate_selection.py`; both the original batch processor and the personal on-demand reader inherit the same policy. The first three sources are compared, expanding when unanimity is absent. One or two valid candidates can use upstream priority degradation, explicitly reported in the reader. Conflicting multi-source content without a supported candidate fails rather than silently choosing an unrelated chapter.
- With no official preview, title alignment is required in addition to the original bounded TOC ranking. Matching chapter numbers alone is insufficient. No official paid preview, AI rewriting or deletion of disputed lines is implied: upstream deletion guards require an official anchor, which this anonymous free-source path does not have.
- On first open, available TOCs are loaded without bodies. The longest catalog supplies the axis; gaps are filled only between adjacent exact anchors. This personal axis is persisted (schema 17); later refreshes only append after an exact tail match, never shift existing progress. New internal gaps cannot be inserted once progress has a stable axis.
- Only the requested chapter is fetched from candidate sources. Each candidate follows the host's combined catalog/chapter timeout budget, clamped to 20–120 seconds; the outer comparison deadline is at least 45 seconds and accommodates the longest candidate budget. Shared fetch slots and at most 64 cached chapters per user (2 MiB each) remain bounded. Downloads use the same personal reader and keep a frozen TOC across pause/restart.
- Legacy shelf IDs, progress, existing downloaded data and covers remain. First online open spends at most 12 seconds discovering matching sources using exact normalized title + author, then at most 10 seconds resolving metadata; an existing single-source axis is preserved. Search-and-add updates sources of an existing aggregate entry. Disabled/unavailable sources are skipped at read time.
- Covers use HTTP(S) image URLs with no-referrer and lazy loading. A named placeholder appears on failure; no arbitrary server-side image proxy is introduced.

Validation includes same-book merging, homonym rejection, missing chapters, outlier voting, source failure/degradation, append-only TOCs, concurrency, old IDs/progress, private caches/downloads and zero full-book work on add. The canonical release gate remains `verify.ps1`; Docker acceptance uses the isolated SG Oracle container because the configured 本地测试 Termark asset is unavailable.

## Personal book detail and chapter catalog (2026-10-07)

Book covers, shelf actions and search-and-add open `/console/library/:bookId`.
This separate detail page follows upstream Hub's metadata, source-map and chapter-state structure.
`GET /api/direct/books/:bookId/overview` requires ownership, loads TOCs only and returns paginated,
searchable chapter summaries with download/cache/on-demand/failure states. It projects cache metadata
without loading chapter bodies; a frozen download TOC remains the chapter axis. Source cards show
catalog status, chapter count, latest title and last catalog query duration. Catalog availability
is not a claim of chapter-body availability. All failed catalogs still show their source diagnostics.
Cached chapters expose existing aggregation audit and selected source, without doing new body checks.

Selecting a chapter opens the immersive reader at `/console/library/:bookId/read?chapter=N`,
validates the index before fetching and starts at position zero. Without an explicit chapter,
the reader resumes saved progress. Exit returns to the catalog. Opening the detail page does
not update progress or start a download. Full-book download remains an explicit action.

## Installable mobile web app

The root `/manifest.webmanifest` defines a stable `/` app ID, `/console/library` launch URL and standalone display. `apple-touch-icon.png` is an opaque 180px icon; 192px, 512px and maskable PNGs support other launchers. Safari-specific meta tags and `viewport-fit=cover` enable an iOS home-screen window. Layout and the immersive reader respect device safe-area insets.

Login and shelf pages provide “添加到主屏幕”. Chromium's deferred installation event is prompted only after a click; iPhone/iPad show Safari share-menu instructions, including the optional “Open as Web App” switch. Already-installed standalone windows hide this entry. OS installation still requires the user's action and iOS may start with a separate login session.

A root-scope service worker handles navigation from the network **without any Cache Storage**; APIs, book data and assets are not intercepted or stored. A failed navigation shows a small reconnect page, not a stale authenticated screen. `index.html`, the worker and manifest revalidate; registration uses `updateViaCache: none`. This adds installability rather than offline reading; saved TXT files remain usable in the device's file app.

## 分类、同步与线路更新（2026-10-07）

`GET /api/direct/sources` 返回 `category`：`light_novel`、`completed`、`ongoing`，对应轻小说、完结、连载中。插件可用 `content.category` 明确指定，轻小说标记优先识别 `light-novel`；全本小说、夜伴书屋和 TXT 整本源归入完结，书香门第附件也归入完结；其余通用在线书源归入连载中。这里分类的是书源用途，通用站点仍可能包含已完结作品。搜索只请求当前分类选中的来源。

进度继续使用服务端原子 revision 校验。浏览器串行提交并合并滚动中的待保存位置，切后台/pagehide 时以 keepalive 提交；返回前台、联网和可见时每 15 秒拉取服务器最新 revision。409 时应用服务器的章节及章内位置，放弃旧设备的过期写入；网络失败保留当前待保存位置并自动重试，同一用户同一本书的暂存位置存于 localStorage。重新打开时仅恢复与服务器 revision 一致的暂存记录。章内位置变化同样会重新定位阅读视图。进度接口禁用 HTTP 缓存，保存时优先检查持久目录，避免重查远端书源拖慢提交。

正文共识、句序检测和缺失量排序继续复用上游 `CandidateSelectionPolicy`。同书识别先转换繁简书名与作者，实际保存仍保留既有书籍 ID。章节匹配允许唯一标题跨较大目录偏移，重复标题必须有邻近锚点，显式卷号冲突不能对齐。初次补目录仅采用双方唯一锚点，刷新既有目录仅追加，保留已有阅读与下载序号。新增 `originIndex` 保留来源本身的章节编号。聚合缓存使用 `policyVersion=2` 并区分自动/手动线路；旧缓存会按需重新验证。

`PUT /api/direct/books/{bookId}/source` 接收 `{sourceBookId: string|null}`，只能选择自己书库中该书已收录的线路；null 恢复自动择优。目录页和阅读器均可选线。手动模式不会退回其他来源，也不复用自动线路的下载正文。`POST .../sources/refresh` 补搜同书线路，保留原书架 ID、进度、下载和选线；`GET .../overview?refresh=true` 真正刷新来源目录，而非只重新请求服务器缓存。附件导入书籍继续使用个人本地文件。
