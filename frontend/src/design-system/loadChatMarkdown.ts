export async function loadChatMarkdown() {
  const { ChatMarkdown } = await import('./ChatMarkdown')
  return { default: ChatMarkdown }
}
