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
