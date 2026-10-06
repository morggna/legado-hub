// Adapted from lukelzlz/legado-server (58c0de5), GPL-3.0. See frontend/third-party/legado-server.md.
import { Icon } from "./icons"
import { defaultReaderSettings, type ReaderSettings } from "./readerSettings"
function SettingRange({ label, value, min, max, step, onChange, display }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void; display: string }) {
  return <label className="setting-range"><span>{label}</span><output>{display}</output><input type="range" min={min} max={max} step={step} value={value} onChange={event => onChange(Number(event.target.value))} /></label>
}

export function ReaderSettingsControls({
  settings,
  onChange,
}: {
  settings: ReaderSettings
  onChange: (next: ReaderSettings) => void
}) {
  const themes = [
    ['light', '晓白'],
    ['paper', '护眼'],
    ['dark', '夜读'],
  ] as const
  const update = (value: Partial<ReaderSettings>) => onChange({ ...settings, ...value })
  return <div className="drawer-scroll-content">
    <section className="setting-section"><span className="setting-label">{'主题'}</span><div className="theme-grid">{themes.map(([theme, label]) => <button type="button" key={theme} className={`theme-choice theme-${theme} ${settings.theme === theme ? 'selected' : ''}`} onClick={() => update({ theme })}><i>{settings.theme === theme && <Icon name="check" />}</i><small>{label}</small></button>)}</div></section>
    <section className="setting-section"><span className="setting-label">{'字体'}</span><label className="font-select"><select aria-label="字体" value={settings.font} onChange={event => update({ font: event.target.value as ReaderSettings['font'] })}><option value="song">{'宋体'}</option><option value="hei">{'黑体 / 苹方'}</option><option value="kai">{'华文楷体'}</option><option value="fangsong">{'华文仿宋'}</option><option value="system">{'系统字体'}</option></select><Icon name="chevronDown" /></label></section>
    <section className="setting-section compact-settings">
      <div className="font-stepper">
        <span>{'字号'}</span>
        <button
          type="button"
          className="subtle-button font-step-btn"
          aria-label={'减小字号'}
          onClick={() => update({ fontSize: Math.max(15, settings.fontSize - 1) })}
        >−</button>
        <output>{settings.fontSize}</output>
        <button
          type="button"
          className="subtle-button font-step-btn"
          aria-label={'增大字号'}
          onClick={() => update({ fontSize: Math.min(28, settings.fontSize + 1) })}
        >+</button>
      </div>
      <SettingRange label={'字间距'} value={settings.letterSpacing} min={-.25} max={1.5} step={.05} display={settings.letterSpacing.toFixed(2)} onChange={letterSpacing => update({ letterSpacing })} />
      <SettingRange label={'行间距'} value={settings.lineHeight} min={1.45} max={2.4} step={.05} display={settings.lineHeight.toFixed(2)} onChange={lineHeight => update({ lineHeight })} />
      <SettingRange label={'段间距'} value={settings.paragraphSpacing} min={.7} max={2} step={.05} display={settings.paragraphSpacing.toFixed(2)} onChange={paragraphSpacing => update({ paragraphSpacing })} />
      <SettingRange label={'左右边距'} value={settings.contentPadding} min={20} max={120} step={2} display={`${settings.contentPadding}`} onChange={contentPadding => update({ contentPadding })} />
      <SettingRange label={'版心宽度'} value={settings.maxWidth} min={560} max={1400} step={20} display={`${settings.maxWidth}px`} onChange={maxWidth => update({ maxWidth })} />
    </section>
    <section className="setting-section"><span className="setting-label">{'翻页方式'}</span><div className="page-modes"><button type="button" className={settings.pageMode === 'scroll' ? 'selected' : ''} onClick={() => update({ pageMode: 'scroll' })}>{'滚动阅读'}</button><button type="button" className={settings.pageMode === 'paginate' ? 'selected' : ''} onClick={() => update({ pageMode: 'paginate' })}>{'平移分页'}</button></div><small className="setting-hint">{settings.pageMode === 'paginate' ? '左右轻扫或点击屏幕两侧平滑翻页' : '垂直滚动阅读，点击上下可快速翻滚'}</small></section>
    <section className="setting-section"><span className="setting-label">{'分栏排版'}</span><div className="page-modes column-modes"><button type="button" className={settings.columnMode === 'auto' ? 'selected' : ''} onClick={() => update({ columnMode: 'auto' })}>{'自适应'}</button><button type="button" className={settings.columnMode === 'single' ? 'selected' : ''} onClick={() => update({ columnMode: 'single' })}>{'单栏'}</button><button type="button" className={settings.columnMode === 'double' ? 'selected' : ''} onClick={() => update({ columnMode: 'double' })}>{'双栏'}</button></div><small className="setting-hint">{settings.columnMode === 'auto' ? '宽屏 (≥800px) 自动开启双页分栏' : settings.columnMode === 'double' ? '固定双栏双页排版' : '固定单栏排版'}</small></section>

    <button type="button" className="reset-settings" onClick={() => onChange({ ...defaultReaderSettings, theme: settings.theme })}>{'恢复默认设置'}</button>
  </div>
}

