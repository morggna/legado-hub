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
proxy is operator-managed; read.uclau.de is allowed. No old accounts, books, cookies
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
