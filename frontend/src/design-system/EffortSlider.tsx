import { useLayoutEffect, useRef, type CSSProperties } from 'react'
import { Slider } from '@heroui/react'

const sparks = [
  [5, 62, 2, -800], [13, 32, 2, -2700], [23, 73, 3, -1400], [31, 43, 2, -3900],
  [39, 21, 2, -600], [48, 67, 3, -3100], [57, 37, 2, -1800], [65, 78, 2, -4200],
  [73, 26, 3, -2200], [81, 58, 2, -1100], [88, 40, 2, -3500], [95, 71, 2, -200],
]

export function EffortSlider({ labels, value, disabled, effect = 'none', valueLabel: suppliedLabel, onChange, onCommit }: {
  labels: string[]; value: number; disabled: boolean; effect?: 'none' | 'ultra' | 'fast'; valueLabel?: string
  onChange: (value: number) => void; onCommit: (value: number) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const valueLabel = suppliedLabel ?? labels[value] ?? '暂无档位'
  // HeroUI's hidden input otherwise announces the numeric index, not the level.
  useLayoutEffect(() => { inputRef.current?.setAttribute('aria-valuetext', valueLabel) }, [valueLabel, disabled])
  const numberValue = (next: number | number[]) => Array.isArray(next) ? next[0] : next
  return <Slider aria-label="思考程度" className="effort-slider" data-effect={effect} data-energized={effect !== 'none' || undefined} minValue={0} maxValue={Math.max(1, labels.length - 1)} step={1}
    value={value} isDisabled={disabled || labels.length < 2}
    onChange={(next) => onChange(numberValue(next))} onChangeEnd={(next) => onCommit(numberValue(next))}>
    <Slider.Track className="effort-slider-track">
      <Slider.Fill className="effort-slider-fill">
        <span className="effort-slider-sparks" aria-hidden="true">
          {sparks.map(([x, y, size, delay], index) => <i key={index} style={{ '--spark-x': `${x}%`, '--spark-y': `${y}%`, '--spark-size': `${size}px`, '--spark-length': `${5 + index % 4}px`, '--spark-brightness': .55 + (index % 4) * .15, '--spark-delay': `${delay}ms`, '--spark-speed': `${900 + (index % 4) * 120}ms` } as CSSProperties} />)}
        </span>
      </Slider.Fill>
      <span className="effort-slider-marks" aria-hidden="true">{labels.map((label, index) => <span key={label + index} style={{ left: `${index / Math.max(1, labels.length - 1) * 100}%` }} data-filled={index <= value || undefined} />)}</span>
      <Slider.Thumb className="effort-slider-thumb" inputRef={inputRef} />
    </Slider.Track>
  </Slider>
}
