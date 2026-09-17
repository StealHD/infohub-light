import { memo } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

function safeHttpUrl(value: string): string | null {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? value : null
  } catch {
    return null
  }
}

const components: Components = {
  a: ({ href, children }) => {
    const safeHref = safeHttpUrl(href ?? '')
    return safeHref
      ? <a href={safeHref} target="_blank" rel="noopener noreferrer" className="text-accent underline decoration-accent/50 underline-offset-[3px]">{children}</a>
      : <span>{children}</span>
  },
  img: ({ alt }) => <span>{alt ?? ''}</span>,
  h1: ({ children }) => <h1 className="type-section-title">{children}</h1>,
  h2: ({ children }) => <h2 className="type-page-title">{children}</h2>,
  h3: ({ children }) => <h3 className="type-card-title">{children}</h3>,
  h4: ({ children }) => <h4 className="type-control">{children}</h4>,
  h5: ({ children }) => <h5 className="type-control">{children}</h5>,
  h6: ({ children }) => <h6 className="type-control">{children}</h6>,
}

const markdownPlugins = [remarkGfm]

export const ChatMarkdown = memo(function ChatMarkdown({ text }: { text: string }) {
  return <div className="chat-markdown min-w-0 max-w-full [overflow-wrap:anywhere]">
    <Markdown
      remarkPlugins={markdownPlugins}
      urlTransform={(url) => safeHttpUrl(url) ?? ''}
      components={components}
    >{text}</Markdown>
  </div>
})
