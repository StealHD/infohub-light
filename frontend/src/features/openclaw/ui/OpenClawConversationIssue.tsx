export function OpenClawConversationIssue({ message, variant }: {
  message: string
  variant: 'compact' | 'workspace'
}) {
  return <p
    role="alert"
    data-openclaw-issue
    className={`${variant === 'workspace' ? 'mx-auto w-full max-w-[var(--inteliscope-width-agent-conversation)]' : 'w-full'} type-body mt-3 min-w-0 break-words text-danger [overflow-wrap:anywhere]`}
  >{message}</p>
}
