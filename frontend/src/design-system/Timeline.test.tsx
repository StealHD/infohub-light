import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Timeline } from './Timeline'

describe('Timeline', () => {
  it('renders a semantic ordered chronology with native attributes', () => {
    render(<Timeline aria-label="发布记录" density="compact" data-owner="design-system">
      <Timeline.Item status="current" data-testid="current-entry">
        <Timeline.Rail>
          <Timeline.Marker data-testid="current-marker" />
          <Timeline.Connector data-testid="current-connector" />
        </Timeline.Rail>
        <Timeline.Content><h2>当前版本</h2></Timeline.Content>
      </Timeline.Item>
      <Timeline.Item data-testid="previous-entry">
        <Timeline.Rail>
          <Timeline.Marker />
          <Timeline.Connector data-testid="last-connector" />
        </Timeline.Rail>
        <Timeline.Content><h2>上一版本</h2></Timeline.Content>
      </Timeline.Item>
    </Timeline>)

    const timeline = screen.getByRole('list', { name: '发布记录' })
    expect(timeline.tagName).toBe('OL')
    expect(timeline).toHaveAttribute('data-density', 'compact')
    expect(timeline).toHaveAttribute('data-owner', 'design-system')
    expect(within(timeline).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByTestId('current-entry')).toHaveAttribute('aria-current', 'true')
    expect(screen.getByTestId('previous-entry')).not.toHaveAttribute('aria-current')
    expect(screen.getByTestId('current-marker')).toHaveAttribute('data-status', 'current')
  })

  it('keeps the chronology rail decorative and hides the final connector through the root contract', () => {
    render(<Timeline aria-label="装饰轨道">
      <Timeline.Item>
        <Timeline.Rail data-testid="rail" aria-hidden={false}>
          <Timeline.Marker data-testid="marker" aria-hidden={false} />
          <Timeline.Connector data-testid="connector" aria-hidden={false} />
        </Timeline.Rail>
        <Timeline.Content>版本</Timeline.Content>
      </Timeline.Item>
    </Timeline>)

    expect(screen.getByTestId('rail')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByTestId('marker')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByTestId('connector')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('list', { name: '装饰轨道' }).className).toContain(
      '[&>[data-timeline-item]:last-child_[data-timeline-connector]]:hidden',
    )
  })
})
