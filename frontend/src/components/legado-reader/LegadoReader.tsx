// Adapted from lukelzlz/legado-server, GPL-3.0. See frontend/third-party/legado-server.md.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { Icon } from './icons'
import { ReaderSettingsControls } from './ReaderSettingsControls'
import { calculatePaginationLayout, isAtBottomBoundary, isAtTopBoundary, isInteractiveReaderTarget, isTapGesture, paginateTapZone, scrollTapZone, splitParagraphs, swipeDirection } from './readerInteractions'
import { getReaderFontFamily, loadReaderSettings, saveReaderSettings, type ReaderSettings } from './readerSettings'
import type { DirectChapter } from '@/lib/direct-api'
import './reader.css'

interface Props {
  userId: string; title: string; chapters: DirectChapter[]; index: number
  sourceStatus?: string
  chapter?: { title: string; content: string }; loading: boolean; error?: string
  position: number; onPosition: (position: number) => void
  onChapter: (index: number, position?: number) => void; onClose: () => void; onRetry: () => void
}
function IconButton({ label, icon, onClick }: {label: string; icon: Parameters<typeof Icon>[0]['name']; onClick: () => void}) {
  return <button type="button" className="reader-icon-button" title={label} aria-label={label} onClick={onClick}><Icon name={icon} /></button>
}

function ChapterList({ chapters, index, onSelect }: {chapters: DirectChapter[]; index: number; onSelect: (i: number) => void}) {
  const ref = useRef<HTMLElement>(null)
  const [top, setTop] = useState(0)
  const [height, setHeight] = useState(600)
  useLayoutEffect(() => {
    const el = ref.current!
    const observer = new ResizeObserver(() => setHeight(el.clientHeight))
    observer.observe(el)
    const active = chapters.findIndex(c => c.index === index)
    el.scrollTop = Math.max(0, active * 40 - el.clientHeight / 2)
    return () => observer.disconnect()
  }, [chapters, index])
  const start = Math.max(0, Math.floor(top / 40) - 8)
  const end = Math.min(chapters.length, Math.ceil((top + height) / 40) + 8)
  return <nav ref={ref} className="reader-chapters" aria-label="章节目录" onScroll={e => setTop(e.currentTarget.scrollTop)}>
    <div style={{ height: start * 40 }} />
    {chapters.slice(start, end).map(c => <button type="button" key={c.index} className={`reader-chapter-item ${c.index === index ? 'current' : ''}`} onClick={() => onSelect(c.index)} title={c.title}><i /><span className="reader-chapter-title">{c.title}</span></button>)}
    <div style={{ height: (chapters.length - end) * 40 }} />
    {!chapters.length && <p className="reader-status">无匹配章节</p>}
  </nav>
}

export function LegadoReader(props: Props) {
  const [settings, setSettings] = useState(() => loadReaderSettings(props.userId))
  const [drawer, setDrawer] = useState<'toc' | 'settings' | null>(null)
  const [tools, setTools] = useState(false)
  const [hint, setHint] = useState(true)
  useEffect(() => {
    const timer = window.setTimeout(() => setHint(false), 3200)
    return () => window.clearTimeout(timer)
  }, [])
  const [query, setQuery] = useState('')
  const [slider, setSlider] = useState<number | null>(null)
  const filtered = useMemo(() => props.chapters.filter(c => c.title.toLowerCase().includes(query.toLowerCase())), [props.chapters, query])
  const updateSettings = (next: ReaderSettings) => { setSettings(next); saveReaderSettings(next, props.userId) }
  const { onChapter, chapters } = props
  const change = useCallback((i: number, pos = 0) => {
    if (i < 0 || i >= chapters.length) return
    onChapter(i, pos)
    setDrawer(null)
  }, [onChapter, chapters.length])
  const style = {
    '--reader-font-family': getReaderFontFamily(settings.font), '--reader-font-size': `${settings.fontSize}px`,
    '--reader-line-height': settings.lineHeight, '--reader-letter-spacing': `${settings.letterSpacing}px`,
    '--reader-paragraph-spacing': `${settings.paragraphSpacing}em`, '--reader-content-padding': `${settings.contentPadding}px`,
    '--reader-max-width': `${settings.maxWidth}px`,
  } as CSSProperties
  const displayed = slider ?? props.index
  return <div className={`legado-reader reader-workspace theme-${settings.theme} ${tools ? 'toolbars-open' : 'toolbars-hidden'}`} style={style} onKeyDown={e => { if (e.key === "Escape" && drawer) { e.stopPropagation(); setDrawer(null) } }}>
    {hint && <div className="reader-immersive-hint" role="status">轻点正文中间，呼出目录和设置</div>}
    <header className="reader-header" inert={!tools || !!drawer}>
      <div className="reader-header-left"><IconButton label="返回书库" icon="arrowLeft" onClick={props.onClose} /><IconButton label="目录" icon="list" onClick={() => setDrawer('toc')} /></div>
      <strong className="reader-header-title">{props.title}</strong>
      <div className="reader-header-actions"><IconButton label="阅读设置" icon="settings" onClick={() => setDrawer('settings')} /></div>
    </header>
    {drawer && <button type="button" className="reader-drawer-backdrop" aria-label="关闭面板" onClick={() => setDrawer(null)} />}
    {drawer === 'toc' && <aside className="reader-drawer reader-drawer-left open" aria-label="目录抽屉">
      <header className="drawer-header"><div className="drawer-title"><Icon name="list" /><strong>目录</strong><small>共 {props.chapters.length} 章</small></div><IconButton label="关闭目录" icon="close" onClick={() => setDrawer(null)} /></header>
      <label className="chapter-search"><Icon name="search" /><input aria-label="搜索章节" placeholder="搜索章节" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <ChapterList chapters={filtered} index={props.index} onSelect={i => change(i)} />
    </aside>}
    {drawer === 'settings' && <aside className="reader-drawer reader-drawer-right open" aria-label="阅读设置面板">
      <header className="drawer-header"><div className="drawer-title"><Icon name="settings" /><strong>阅读设置</strong></div><IconButton label="关闭设置" icon="close" onClick={() => setDrawer(null)} /></header>
      <ReaderSettingsControls settings={settings} onChange={updateSettings} />
    </aside>}
    <main className="reader-main" inert={!!drawer}>
      {props.error && <div className="reader-error-banner" role="alert">{props.error} <button type="button" onClick={props.onRetry}>重试</button></div>}
      {props.loading ? <p className="reader-status" role="status">正在获取当前章节…</p> : props.chapter && <ChapterCanvas key={props.index} chapter={props.chapter} settings={settings} position={props.position} onPosition={props.onPosition} onPrevious={() => change(props.index - 1, 1)} onNext={() => change(props.index + 1)} onToggle={() => { setHint(false); setTools(v => !v) }} paused={!!drawer} />}
    </main>
    <footer className="reader-floating-footer" inert={!tools || !!drawer}>
      {props.sourceStatus && <p className="reader-source-status">{props.sourceStatus}</p>}
      <div className="reader-chapter-control-bar">
        <button type="button" className="reader-chapter-btn" disabled={props.index === 0} onClick={() => change(props.index - 1)}><Icon name="arrowLeft" />上一章</button>
        <div className="reader-chapter-slider-wrap"><div className="reader-chapter-info"><span className="chapter-num">{displayed + 1} / {props.chapters.length || '…'}</span><span className="chapter-name">{props.chapters[displayed]?.title}</span></div>
          <input aria-label="跳转章节" className="reader-chapter-slider" type="range" min={0} max={Math.max(0, props.chapters.length - 1)} value={displayed} style={{'--slider-percent': `${displayed / Math.max(1, props.chapters.length - 1) * 100}%`} as CSSProperties} onChange={e => setSlider(Number(e.target.value))} onPointerUp={e => { change(Number(e.currentTarget.value)); setSlider(null) }} onKeyUp={e => { if (['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) { change(Number(e.currentTarget.value)); setSlider(null) } }} />
        </div>
        <button type="button" className="reader-chapter-btn" disabled={props.index + 1 >= props.chapters.length} onClick={() => change(props.index + 1)}>下一章<Icon name="arrowRight" /></button>
      </div>
    </footer>
  </div>
}

function ChapterCanvas({ chapter, settings, position, onPosition, onPrevious, onNext, onToggle, paused }: {
  chapter: {title: string; content: string}; settings: ReaderSettings; position: number
  onPosition: (p: number) => void; onPrevious: () => void; onNext: () => void; onToggle: () => void; paused: boolean
}) {
  const viewport = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLElement>(null)
  const location = useRef(position)
  const restoring = useRef(true)
  const [page, setPage] = useState(0)
  const [layout, setLayout] = useState({columnWidth: 800, stride: 840, pageCount: 1, isDoubleColumn: false})
  const down = useRef<{x: number; y: number} | null>(null)
  const wheelTime = useRef(0)
  const paginated = settings.pageMode === 'paginate'
  const paragraphs = useMemo(() => splitParagraphs(chapter.content), [chapter.content])
  useLayoutEffect(() => {
    const el = viewport.current!
    const article = body.current!
    let frame = 0
    let active = true
    const measure = () => {
      if (!active) return
      restoring.current = true
      if (paginated) {
        const columns = calculatePaginationLayout({viewportWidth: el.clientWidth, totalScrollWidth: 0, columnMode: settings.columnMode})
        article.style.columnWidth = `${columns.columnWidth}px`
        const next = calculatePaginationLayout({viewportWidth: el.clientWidth, totalScrollWidth: article.scrollWidth, columnMode: settings.columnMode})
        setLayout(next)
        setPage(Math.round(location.current * Math.max(0, next.pageCount - 1)))
      } else {
        el.scrollTop = location.current * Math.max(0, el.scrollHeight - el.clientHeight)
      }
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => { restoring.current = false })
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    void document.fonts?.ready.then(measure)
    return () => { active = false; observer.disconnect(); cancelAnimationFrame(frame) }
  }, [paginated, settings, chapter.content])
  const turn = useCallback((delta: number) => {
    if (paused || restoring.current) return
    const el = viewport.current!
    if (paginated) {
      const next = page + delta
      if (next < 0) { onPrevious(); return }
      if (next >= layout.pageCount) { onNext(); return }
      setPage(next)
      location.current = next / Math.max(1, layout.pageCount - 1)
      onPosition(location.current)
    } else if (delta < 0 && isAtTopBoundary(el.scrollTop)) onPrevious()
    else if (delta > 0 && isAtBottomBoundary(el.scrollTop, el.scrollHeight, el.clientHeight)) onNext()
    else el.scrollBy({top: delta * el.clientHeight * .85, behavior: 'smooth'})
  }, [paused, paginated, page, layout.pageCount, onPrevious, onNext, onPosition])
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (paused || isInteractiveReaderTarget(e.target)) return
      if (['ArrowRight','PageDown',' '].includes(e.key)) { e.preventDefault(); turn(1) }
      if (['ArrowLeft','PageUp'].includes(e.key)) { e.preventDefault(); turn(-1) }
      if (e.key === 'Escape') onToggle()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [turn, paused, onToggle])
  const pointerUp = (e: PointerEvent) => {
    const start = down.current; down.current = null
    if (!start || paused || window.getSelection()?.toString()) return
    const rect = e.currentTarget.getBoundingClientRect()
    const swipe = swipeDirection(start.x, start.y, e.clientX, e.clientY)
    if (paginated && swipe) { turn(swipe === 'left' ? 1 : -1); return }
    if (!isTapGesture(start.x, start.y, e.clientX, e.clientY)) return
    const zone = paginated ? paginateTapZone(e.clientX - rect.left, rect.width) : scrollTapZone(e.clientY - rect.top, rect.height)
    if (zone === 'toggle') onToggle(); else turn(zone === 'next' ? 1 : -1)
  }
  const text = <><h1>{chapter.title}</h1>{paragraphs.map((p, i) => <p key={i}>{p}</p>)}</>
  return <section className={paginated ? 'reader-paginated-wrap' : 'reader-scroll-wrap'} onPointerDown={e => { if (e.button === 0 && !isInteractiveReaderTarget(e.target)) down.current = {x:e.clientX,y:e.clientY} }} onPointerUp={pointerUp} onPointerCancel={() => { down.current = null }} onWheel={e => { if (paginated && Math.abs(e.deltaY) > 25 && Date.now() - wheelTime.current > 250) { wheelTime.current = Date.now(); turn(e.deltaY > 0 ? 1 : -1) } }}>
    {paginated ? <><div ref={viewport} className={`reader-paginated-viewport ${layout.isDoubleColumn ? 'is-double-column' : ''}`}><div className="reader-paginated-track" style={{transform: `translateX(-${page * layout.stride}px)`}}><article ref={body} className="reader-paginated-column-body" style={{columnWidth: layout.columnWidth, columnGap: 40}}>{text}</article></div></div><div className="reader-paginated-footer"><span>{chapter.title}</span><span>{page + 1} / {layout.pageCount}</span></div></> : <div className="reader-scroll-viewport" ref={viewport} onScroll={e => {
      if (restoring.current) return
      const el = e.currentTarget
      location.current = Math.min(1, Math.max(0, el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight)))
      onPosition(location.current)
    }}><article className="reading-content" ref={body}>{text}<div className="reader-end"><button type="button" className="reader-chapter-btn" onClick={onNext}>继续下一章<Icon name="arrowRight" /></button></div></article></div>}
  </section>
}
