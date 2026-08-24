import type { SVGProps } from 'react'

export {
  Archive,
  ArrowDown,
  ArrowDownUp,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  Bell,
  BellRing,
  BookMarked,
  BookOpen,
  Bookmark,
  BookmarkCheck,
  Bot,
  BrushCleaning,
  ChartNoAxesCombined,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CircleCheck,
  CircleDashed,
  CircleSlash2,
  CircleStop,
  CircleX,
  Clock3,
  ClockAlert,
  Copy,
  Database,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  FileWarning,
  FlaskConical,
  FoldVertical,
  GitCompareArrows,
  Globe2,
  HardDrive,
  History,
  Image,
  ImageOff,
  ImagePlus,
  KeyRound,
  Layers3,
  LayoutDashboard,
  ListChecks,
  LoaderCircle,
  Lock,
  LockKeyhole,
  LogOut,
  Menu,
  MessageCircle,
  Moon,
  MoreHorizontal,
  Palette,
  Pause,
  Pencil,
  Play,
  Plus,
  Power,
  Radio,
  RadioTower,
  RefreshCw,
  Rocket,
  RotateCcw,
  Route,
  Rows3,
  Rss,
  Save,
  ScrollText,
  Search,
  Send,
  Settings,
  Settings2,
  Share2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Square,
  Star,
  Stethoscope,
  Sun,
  SunMoon,
  Tags,
  Trash2,
  TriangleAlert,
  UnfoldVertical,
  Unplug,
  UserPlus,
  UserRound,
  Users,
  Waypoints,
  WifiOff,
  X,
} from 'lucide-react'

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
      pointerEvents="none"
    />
  </svg>
}

export function InteliscopeMark({ size = 20, ...props }: Omit<SplitPanelProps, 'open'>) {
  return <svg
    {...props}
    data-inteliscope-mark
    width={size}
    height={size}
    viewBox="0 0 64 64"
    fill="currentColor"
  >
    <path d="M56 10.5C46.5 12.5 35.5 16.3 29 20.5c-4.5 2.9-3.9 6.6-3.2 9.5.9 3 .1 5.6-3 6.3-4 1-8-1.5-10-4.5-2.8-4-1.9-8.5 1-12.3C20.5 10.9 39.3 8.9 53.8 9.9c2 .1 2.6.3 2.2.6Z" />
    <path d="M8.2 53.3c9-3.8 20.3-7.5 26.5-12.6 3.8-3.1 5.4-6.9 4.8-10-.6-3 1.6-5.3 5.1-5.5 4.2-.3 8.6 2.8 10.3 7.2 2.4 6.3-1.3 12.2-7.4 15.7-7.8 4.6-18.7 5.8-29.6 6.2-6.6.3-10.9.1-9.7-1Z" />
  </svg>
}
