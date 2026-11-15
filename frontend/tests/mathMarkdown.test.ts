// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '../src/htmlArtifacts'

const dom = (source:string) => { const el = document.createElement('div'); el.innerHTML = renderMarkdown(source); return el }
describe('safe math in historical and streaming Markdown', () => {
  for (const source of [String.raw`中文 $\frac{1}{2}$ 公式`, String.raw`\(\sqrt{x}\)`,
    String.raw`$$\begin{matrix}1&2\\3&4\end{matrix}$$`,
    String.raw`\[\begin{aligned}a&=b+c\\d&=e\end{aligned}\]`, '$$\nx^2\n$$']) {
    it(`renders ${source}`, () => {
      const el = dom(source)
      expect(el.querySelector('.katex')).not.toBeNull()
      expect(el.querySelector('math')).not.toBeNull()
    })
  }
  it('keeps code, escapes and currency literal', () => {
    const el = dom('`$x$`\n\n```latex\n\\[x\\]\n```\n\n价格 \\$5，另付 10 元')
    expect(el.querySelector('.katex')).toBeNull()
    expect(el.querySelector('code')?.textContent).toBe('$x$')
    expect(el.textContent).toContain('$5')
  })
  it('waits for a complete streaming delimiter', () => {
    const source = String.raw`推导 \[\frac{x}{2}`
    expect(dom(source).querySelector('.katex')).toBeNull()
    expect(dom(source).textContent?.trim()).toBe(source)
    expect(dom(source + String.raw`\]`).querySelector('.katex')).not.toBeNull()
    expect(dom('$$x').querySelector('.katex')).toBeNull()
  })
  it('falls back for invalid TeX and blocks trusted commands and HTML', () => {
    expect(dom(String.raw`$\frac{1}{$`).querySelector('.katex-error')).not.toBeNull()
    const el = dom(String.raw`$\href{javascript:alert(1)}{click}$ $\htmlClass{evil}{x}$ <img src=x onerror=alert(1)>`)
    expect(el.querySelector('script,img,iframe,.evil,[onclick],[onerror],a[href^="javascript:"]')).toBeNull()
  })
})
