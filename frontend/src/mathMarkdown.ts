import katex from 'katex'
import type { MarkedExtension } from 'marked'

// Tokenize before Markdown consumes backslash delimiters; code tokens stay opaque.
export const mathMarkdown: MarkedExtension = {
  extensions: [{
    name: 'math', level: 'inline',
    start: source => source.search(/\$|\\[([]/),
    tokenizer(source) {
      const delimiters = [['$$', '$$', true], ['\\[', '\\]', true], ['\\(', '\\)', false], ['$', '$', false]] as const
      for (const [open, close, displayMode] of delimiters) {
        if (!source.startsWith(open)) continue
        let end = open.length
        while ((end = source.indexOf(close, end)) !== -1) {
          let backslashes = 0
          for (let i = end - 1; i >= 0 && source[i] === '\\'; i--) backslashes++
          if (backslashes % 2) { end += close.length; continue }
          const text = source.slice(open.length, end)
          if (!text.trim() || (!displayMode && text.includes('\n'))) return
          return { type: 'math', raw: source.slice(0, end + close.length), text, displayMode }
        }
        if (open !== '$') return {type: 'math', raw: source, text: source, pending: true}
        return
      }
    },
    renderer(token) {
      if (token.pending || token.text.length > 20000) {
        return token.raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
      }
      return katex.renderToString(token.text, {
        displayMode: token.displayMode, throwOnError: false, trust: false,
        strict: 'ignore', maxExpand: 500, maxSize: 20, output: 'htmlAndMathml',
      })
    },
  }],
}
