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
- Only the requested chapter is fetched from candidate sources. There is a 45-second chapter comparison budget, 20-second per-source budget, shared fetch slots, and at most 64 cached chapters per user (2 MiB each). Downloads use the same personal reader and keep a frozen TOC across pause/restart.
- Legacy shelf IDs, progress, existing downloaded data and covers remain. First online open spends at most 12 seconds discovering matching sources using exact normalized title + author, then at most 10 seconds resolving metadata; an existing single-source axis is preserved. Search-and-add updates sources of an existing aggregate entry. Disabled/unavailable sources are skipped at read time.
- Covers use HTTP(S) image URLs with no-referrer and lazy loading. A named placeholder appears on failure; no arbitrary server-side image proxy is introduced.

Validation includes same-book merging, homonym rejection, missing chapters, outlier voting, source failure/degradation, append-only TOCs, concurrency, old IDs/progress, private caches/downloads and zero full-book work on add. The canonical release gate remains `verify.ps1`; Docker acceptance uses the isolated SG Oracle container because the configured 本地测试 Termark asset is unavailable.
