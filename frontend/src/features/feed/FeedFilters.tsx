import {
  Box,
  Chip,
  FilterPopover,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '../../ui'
import type { FeedMode } from './feedModel'

type FeedFiltersProps = {
  showModes?: boolean
  mode: FeedMode
  onModeChange: (mode: FeedMode) => void
  unreadFirst: boolean
  onUnreadFirstChange: (value: boolean) => void
  sourceId: string
  onSourceChange: (value: string) => void
  channel: string
  onChannelChange: (value: string) => void
  topic: string
  onTopicChange: (value: string) => void
  minScore?: number
  onMinScoreChange: (value: number | undefined) => void
  sources: ReadonlyArray<readonly [string, string]>
  channels: string[]
  topics: string[]
  onClear: () => void
  updatedLabel?: string
}

function NativeFilter({ id, label, value, onChange, children }: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
}) {
  return <FormControl fullWidth size="small">
    <InputLabel id={`${id}-label`}>{label}</InputLabel>
    <Select
      id={id}
      labelId={`${id}-label`}
      value={value}
      label={label}
      onChange={(event) => onChange(String(event.target.value))}
    >{children}</Select>
  </FormControl>
}

export function FeedFilters(props: FeedFiltersProps) {
  const activeCount = [props.sourceId, props.channel, props.topic, props.minScore].filter((value) => value !== '' && value !== undefined).length
  const sourceLabel = props.sources.find(([value]) => value === props.sourceId)?.[1] ?? props.sourceId

  return <Stack spacing={1.25}>
    {props.showModes && <Tabs
      value={props.mode}
      onChange={(_event, value: FeedMode) => props.onModeChange(value)}
      aria-label="信息流模式"
      variant="fullWidth"
    >
      <Tab value="featured" label="精选" />
      <Tab value="all" label="全部" />
      <Tab value="daily" label="日报" />
    </Tabs>}
    <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
      <Chip
        label="未读优先"
        color={props.unreadFirst ? 'primary' : 'default'}
        variant={props.unreadFirst ? 'filled' : 'outlined'}
        onClick={() => props.onUnreadFirstChange(!props.unreadFirst)}
      />
      {props.sourceId && <Chip label={`来源：${sourceLabel}`} color="primary" variant="outlined" onClick={() => props.onSourceChange('')} />}
      {props.channel && <Chip label={`频道：${props.channel}`} color="primary" variant="outlined" onClick={() => props.onChannelChange('')} />}
      {props.topic && <Chip label={`主题：${props.topic}`} color="primary" variant="outlined" onClick={() => props.onTopicChange('')} />}
      {props.minScore !== undefined && <Chip label={`最低分：${props.minScore}+`} color="primary" variant="outlined" onClick={() => props.onMinScoreChange(undefined)} />}
      <Box sx={{ ml: 'auto' }}>
        <FilterPopover dialogLabel="筛选信息流" activeCount={activeCount}>
          <Stack spacing={2}>
            <Typography variant="h3">筛选信息流</Typography>
            <NativeFilter id="feed-source-filter" label="来源筛选" value={props.sourceId} onChange={props.onSourceChange}>
              <MenuItem value="">全部来源</MenuItem>
              {props.sources.map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}
            </NativeFilter>
            <NativeFilter id="feed-channel-filter" label="频道筛选" value={props.channel} onChange={props.onChannelChange}>
              <MenuItem value="">全部频道</MenuItem>
              {props.channels.map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
            </NativeFilter>
            <NativeFilter id="feed-topic-filter" label="主题筛选" value={props.topic} onChange={props.onTopicChange}>
              <MenuItem value="">全部主题</MenuItem>
              {props.topics.map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
            </NativeFilter>
            <NativeFilter id="feed-score-filter" label="最低分筛选" value={props.minScore?.toString() ?? ''} onChange={(value) => props.onMinScoreChange(value ? Number(value) : undefined)}>
              <MenuItem value="">不限</MenuItem>
              {[6, 7, 8, 9].map((value) => <MenuItem key={value} value={value}>{value}+</MenuItem>)}
            </NativeFilter>
            {activeCount > 0 && <Chip label="清除全部筛选" onClick={props.onClear} />}
          </Stack>
        </FilterPopover>
      </Box>
    </Stack>
    {props.updatedLabel && <Typography variant="caption" color="text.secondary">{props.updatedLabel}</Typography>}
  </Stack>
}
