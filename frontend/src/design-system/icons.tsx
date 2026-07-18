import type { SVGProps } from 'react'

export * from 'lucide-react'

type SplitPanelProps = SVGProps<SVGSVGElement> & {
  open?: boolean
  size?: number | string
}

export function SplitPanel({ open = false, size = 18, ...props }: SplitPanelProps) {
  return <svg
    {...props}
    data-split-panel-icon
    width={size}
    height={size}
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <rect x="2.25" y="2.25" width="15.5" height="15.5" rx="3.25" />
    <path d="M11.75 2.75v14.5" />
    <rect
      data-panel-fill
      x="12"
      y="2.75"
      width="5.25"
      height="14.5"
      rx="2.5"
      fill="currentColor"
      stroke="none"
      opacity={open ? '0.16' : '0'}
    />
  </svg>
}

export function InteliscopeMark({ size = 20, ...props }: Omit<SplitPanelProps, 'open'>) {
  return <svg
    {...props}
    data-inteliscope-mark
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.65"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <circle cx="12" cy="12" r="7.75" opacity="0.55" />
    <path d="M12 4.25v2.2M12 17.55v2.2M4.25 12h2.2M17.55 12h2.2" opacity="0.8" />
    <path d="M12 12l4.8-3.1" />
    <circle cx="12" cy="12" r="2.15" fill="currentColor" stroke="none" />
  </svg>
}
