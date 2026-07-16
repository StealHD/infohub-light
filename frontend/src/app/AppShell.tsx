import type { MouseEvent, ReactNode } from 'react'
import { useState } from 'react'
import {
  AccountCircleRounded,
  BookmarkBorderRounded,
  ChevronLeftRounded,
  ChevronRightRounded,
  CloseRounded,
  ExpandMoreRounded,
  HistoryRounded,
  LogoutRounded,
  NotificationsNoneRounded,
  RadioRounded,
  RefreshRounded,
  SearchRounded,
  SettingsRounded,
  StarBorderRounded,
} from '../ui/icons'
import { NavLink, useLocation } from 'react-router-dom'

import type { User } from '../api/types'
import {
  Alert,
  AppBar,
  BottomNavigation,
  BottomNavigationAction,
  Box,
  Button,
  Drawer,
  IconButton,
  InputAdornment,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Snackbar,
  Stack,
  TextField,
  Toolbar,
  Tooltip,
  Typography,
  uiLayout,
  uiRadii,
  useMediaQuery,
  useTheme,
} from '../ui'
import { readSidebarPreference, writeSidebarPreference } from './sidebarPreference'

type RefreshState = 'idle' | 'pending' | 'queued' | 'running' | 'partial' | 'failed' | 'succeeded' | 'blocked'

type AppShellProps = {
  user: User
  query: string
  onQueryChange: (value: string) => void
  onRefresh?: () => void
  onLogout?: () => void
  onRetry?: () => void
  refreshState: RefreshState
  refreshMessage?: string
  refreshEventKey?: string
  children: ReactNode
}

const navItems = [
  { to: '/feed', label: '信息流', icon: RadioRounded },
  { to: '/later', label: '稍后读', icon: BookmarkBorderRounded },
  { to: '/saved', label: '收藏', icon: StarBorderRounded },
  { to: '/history', label: '历史', icon: HistoryRounded },
  { to: '/subscriptions', label: '订阅', icon: NotificationsNoneRounded },
]

const mobileNavItems = [...navItems, { to: '/settings', label: '设置', icon: SettingsRounded }]

const roleLabels: Record<User['role'], string> = {
  owner: '所有者',
  admin: '管理员',
  member: '成员',
  viewer: '只读查看者',
}

function severityFor(state: RefreshState): 'success' | 'warning' | 'error' | 'info' {
  if (state === 'failed') return 'error'
  if (state === 'partial' || state === 'blocked') return 'warning'
  if (state === 'succeeded') return 'success'
  return 'info'
}

export function AppShell(props: AppShellProps) {
  const theme = useTheme()
  const location = useLocation()
  const mobile = useMediaQuery('(max-width:767px)')
  const wideDesktop = useMediaQuery(theme.breakpoints.up('lg'))
  const [sidebarState, setSidebarState] = useState(() => ({ userId: props.user.id, value: readSidebarPreference(props.user.id) }))
  const [accountAnchor, setAccountAnchor] = useState<HTMLElement | null>(null)
  const [dismissedEvent, setDismissedEvent] = useState('')
  const sidebarPreference = sidebarState.userId === props.user.id ? sidebarState.value : readSidebarPreference(props.user.id)
  const expanded = sidebarPreference === 'expanded'
  const refreshing = props.refreshState === 'pending' || props.refreshState === 'queued' || props.refreshState === 'running'
  const accountName = props.user.display_name || props.user.username
  const permanentWidth = wideDesktop && expanded ? uiLayout.expandedDrawerWidth : uiLayout.collapsedDrawerWidth
  const overlayOpen = !mobile && !wideDesktop && expanded
  const noticeKey = props.refreshEventKey || `${props.refreshState}:${props.refreshMessage ?? ''}`
  const noticeOpen = Boolean(props.refreshMessage) && props.refreshState !== 'running' && dismissedEvent !== noticeKey
  const noticeDuration = props.refreshState === 'failed' || props.refreshState === 'partial' || props.refreshState === 'blocked' ? 8000 : 4000

  function closeNotice(_event?: unknown, reason?: string) {
    if (reason === 'clickaway') return
    setDismissedEvent(noticeKey)
  }

  function setExpanded(next: boolean) {
    const value = next ? 'expanded' : 'collapsed'
    setSidebarState({ userId: props.user.id, value })
    writeSidebarPreference(props.user.id, value)
  }

  function sidebarContents(showLabels: boolean, closeOverlay?: () => void) {
    const itemSx = {
      flex: '0 0 auto',
      minHeight: 48,
      mx: 1,
      my: 0.5,
      px: showLabels ? 1.5 : 0,
      justifyContent: showLabels ? 'flex-start' : 'center',
      borderRadius: `${uiRadii.control}px`,
      color: 'text.secondary',
      '&.Mui-selected': {
        bgcolor: 'primaryContainer',
        color: 'onPrimaryContainer',
        '&:hover': { bgcolor: 'primaryContainer' },
      },
    }
    const nav = (to: string, label: string, Icon: typeof RadioRounded) => <Tooltip key={to} title={showLabels ? '' : label} placement="right">
      <ListItemButton
        component={NavLink}
        to={to}
        selected={location.pathname === to}
        aria-label={label}
        onClick={closeOverlay}
        sx={itemSx}
      >
        <ListItemIcon sx={{ minWidth: 0, mr: showLabels ? 1.5 : 0, justifyContent: 'center', color: 'inherit' }}>
          <Icon fontSize="small" />
        </ListItemIcon>
        {showLabels && <ListItemText primary={label} slotProps={{ primary: { sx: { fontSize: 14, fontWeight: 650 } } }} />}
      </ListItemButton>
    </Tooltip>

    return <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', py: 1 }}>
      <Tooltip title={showLabels ? '' : (expanded ? '收起侧栏' : '展开侧栏')} placement="right">
        <ListItemButton
          type="button"
          aria-label={expanded ? '收起侧栏' : '展开侧栏'}
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
          sx={{ ...itemSx, mb: 1, color: 'text.primary' }}
        >
          <ListItemIcon sx={{ minWidth: 0, mr: showLabels ? 1.5 : 0, justifyContent: 'center', color: 'inherit' }}>
            {expanded ? <ChevronLeftRounded fontSize="small" /> : <ChevronRightRounded fontSize="small" />}
          </ListItemIcon>
          {showLabels && <ListItemText primary="收起侧栏" slotProps={{ primary: { sx: { fontSize: 14, fontWeight: 650 } } }} />}
        </ListItemButton>
      </Tooltip>
      <List component="nav" aria-label="主导航" disablePadding>
        {navItems.map(({ to, label, icon }) => nav(to, label, icon))}
      </List>
      <Stack role="group" aria-label="账户与设置" spacing={0.5} sx={{ mt: 'auto' }}>
        {nav('/settings', '设置', SettingsRounded)}
        <Tooltip title={showLabels ? '' : accountName} placement="right">
          <ListItemButton
            type="button"
            aria-label={`账户 ${accountName}`}
            aria-haspopup="menu"
            aria-controls={accountAnchor ? 'account-menu' : undefined}
            aria-expanded={Boolean(accountAnchor)}
            onClick={(event: MouseEvent<HTMLElement>) => {
              const anchor = event.currentTarget
              setAccountAnchor((current) => current ? null : anchor)
            }}
            sx={{
              ...itemSx,
              color: 'text.primary',
              bgcolor: showLabels ? 'surfaceContainerHigh' : 'transparent',
            }}
          >
            <ListItemIcon sx={{ minWidth: 0, mr: showLabels ? 1.5 : 0, justifyContent: 'center', color: 'inherit' }}>
              <AccountCircleRounded fontSize="small" />
            </ListItemIcon>
            {showLabels && <Box sx={{ minWidth: 0, flex: 1, textAlign: 'left' }}>
              <Typography noWrap sx={{ fontSize: 14, fontWeight: 700, lineHeight: 1.25 }}>{accountName}</Typography>
              <Typography variant="caption" color="text.secondary">{roleLabels[props.user.role]}</Typography>
            </Box>}
            {showLabels && <ExpandMoreRounded fontSize="small" sx={{ color: 'text.secondary' }} />}
          </ListItemButton>
        </Tooltip>
      </Stack>
    </Box>
  }

  return <Box sx={{
    height: '100dvh',
    display: 'grid',
    gridTemplateRows: `${uiLayout.appBarHeight}px minmax(0, 1fr)`,
    gridTemplateColumns: mobile ? 'minmax(0, 1fr)' : `${permanentWidth}px minmax(0, 1fr)`,
    bgcolor: 'background.default',
    overflow: 'hidden',
    transition: theme.transitions.create('grid-template-columns', { duration: theme.transitions.duration.shortest }),
  }}>
    <AppBar position="static" color="transparent" sx={{ gridColumn: '1 / -1', borderBottom: 1, borderColor: 'divider', bgcolor: 'background.default' }}>
      <Toolbar sx={{ minHeight: `${uiLayout.appBarHeight}px !important`, gap: { xs: 1, md: 3 }, px: { xs: 1.5, md: 2.5 } }}>
        <Box sx={{ minWidth: { md: 220 } }}>
          <Typography variant="h6" component="strong" sx={{ display: 'block', fontWeight: 800, letterSpacing: '-0.04em' }}>Inteliscope</Typography>
          {!mobile && <Typography variant="caption" color="text.secondary">PRIVATE INTELLIGENCE BRIEFING</Typography>}
        </Box>
        <TextField
          hiddenLabel
          type="search"
          placeholder="搜索标题、概括、来源与主题"
          value={props.query}
          onChange={(event) => props.onQueryChange(event.target.value)}
          size="small"
          fullWidth
          slotProps={{
            htmlInput: { 'aria-label': '搜索信息流' },
            input: { startAdornment: <InputAdornment position="start"><SearchRounded fontSize="small" /></InputAdornment> },
          }}
          sx={{ maxWidth: 720, mx: 'auto', '& .MuiOutlinedInput-root': { bgcolor: 'surfaceContainerHigh' } }}
        />
        <Button
          type="button"
          variant="contained"
          aria-label={refreshing ? (props.refreshState === 'pending' ? '提交更新中' : props.refreshState === 'queued' ? '更新已排队' : '更新中') : '更新信息流'}
          title="从全部已启用订阅抓取、去重并整理新内容，不会修改订阅设置"
          onClick={props.onRefresh}
          disabled={refreshing || !props.onRefresh}
          startIcon={<RefreshRounded sx={refreshing ? { animation: 'spin 1s linear infinite' } : undefined} />}
          sx={{ flex: '0 0 auto', px: { xs: 1.25, sm: 2 }, '& .MuiButton-startIcon': { mr: { xs: 0, sm: 1 } } }}
        >
          <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' } }}>{refreshing ? (props.refreshState === 'queued' ? '更新已排队' : '更新中') : '更新信息流'}</Box>
        </Button>
      </Toolbar>
    </AppBar>

    {!mobile && <Drawer
      variant="permanent"
      open
      slotProps={{ paper: { className: 'sidebar-permanent' } }}
      sx={{
        gridRow: 2,
        gridColumn: 1,
        width: permanentWidth,
        minHeight: 0,
        '& .MuiDrawer-paper': {
          position: 'relative',
          width: permanentWidth,
          height: '100%',
          overflowX: 'hidden',
          boxSizing: 'border-box',
          borderRight: 0,
          bgcolor: 'surfaceContainer',
          transition: theme.transitions.create('width', { duration: theme.transitions.duration.shortest }),
        },
      }}
    >{sidebarContents(wideDesktop && expanded)}</Drawer>}

    {!mobile && !wideDesktop && <Drawer
      variant="temporary"
      open={overlayOpen}
      onClose={() => setExpanded(false)}
      slotProps={{ paper: { className: 'sidebar-overlay', sx: { width: uiLayout.expandedDrawerWidth, bgcolor: 'surfaceContainer' } } }}
    >{sidebarContents(true, () => setExpanded(false))}</Drawer>}

    <Box component="main" sx={{
      gridRow: 2,
      gridColumn: mobile ? 1 : 2,
      minWidth: 0,
      minHeight: 0,
      overflow: mobile ? 'visible' : 'hidden',
      pb: mobile ? `${uiLayout.mobileNavHeight}px` : 0,
    }}>
      {props.children}
    </Box>

    {mobile && <BottomNavigation
      component="nav"
      aria-label="移动端主导航"
      showLabels
      value={mobileNavItems.find(({ to }) => location.pathname === to)?.to ?? false}
      sx={{ position: 'fixed', zIndex: theme.zIndex.appBar, left: 0, right: 0, bottom: 0, height: uiLayout.mobileNavHeight, borderTop: 1, borderColor: 'divider' }}
    >
      {mobileNavItems.map(({ to, label, icon: Icon }) => <BottomNavigationAction
        key={to}
        component={NavLink}
        to={to}
        value={to}
        label={label}
        icon={<Icon fontSize="small" />}
        sx={{ minWidth: 0, px: 0.25 }}
      />)}
    </BottomNavigation>}

    <Snackbar
      open={noticeOpen}
      autoHideDuration={noticeDuration}
      onClose={closeNotice}
      anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      sx={{ top: `${uiLayout.appBarHeight + 10}px !important` }}
    >
      <Alert
        severity={severityFor(props.refreshState)}
        variant="filled"
        action={<Stack direction="row" spacing={0.5}>
          {(props.refreshState === 'partial' || props.refreshState === 'failed') && <Button component={NavLink} to="/subscriptions?health=problem" color="inherit" size="small">失败来源</Button>}
          {props.refreshState === 'failed' && props.onRetry && <Button color="inherit" size="small" onClick={props.onRetry}>重试</Button>}
          <IconButton aria-label="关闭通知" color="inherit" size="small" onClick={() => closeNotice()}><CloseRounded fontSize="small" /></IconButton>
        </Stack>}
      >{props.refreshMessage}</Alert>
    </Snackbar>

    <Menu
      id="account-menu"
      anchorEl={accountAnchor}
      open={Boolean(accountAnchor)}
      onClose={() => setAccountAnchor(null)}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      slotProps={{ paper: { sx: { ml: 1 } } }}
    >
      <Box sx={{ px: 2, py: 1 }}><Typography sx={{ fontWeight: 700 }}>{accountName}</Typography><Typography variant="caption" color="text.secondary">{roleLabels[props.user.role]}</Typography></Box>
      {props.onLogout && <MenuItem onClick={props.onLogout}><LogoutRounded fontSize="small" sx={{ mr: 1 }} />退出登录</MenuItem>}
    </Menu>
  </Box>
}
