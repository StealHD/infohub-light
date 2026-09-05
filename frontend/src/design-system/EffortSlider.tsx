import { useLayoutEffect, useRef } from 'react'
import { Slider } from '@heroui/react'

export function EffortSlider({ labels, value, disabled, energized = false, valueLabel: suppliedLabel, onChange, onCommit }: {
  labels: string[]; value: number; disabled: boolean; energized?: boolean; valueLabel?: string
  onChange: (value: number) => void; onCommit: (value: number) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const valueLabel = suppliedLabel ?? labels[value] ?? '暂无档位'
  // HeroUI's hidden input otherwise announces the numeric index, not the level.
  useLayoutEffect(() => { inputRef.current?.setAttribute('aria-valuetext', valueLabel) }, [valueLabel, disabled])
  const numberValue = (next: number | number[]) => Array.isArray(next) ? next[0] : next
  return <Slider aria-label="思考程度" className="effort-slider" data-energized={energized || undefined} minValue={0} maxValue={Math.max(1, labels.length - 1)} step={1}
    value={value} isDisabled={disabled || labels.length < 2}
    onChange={(next) => onChange(numberValue(next))} onChangeEnd={(next) => onCommit(numberValue(next))}>
    <Slider.Track className="effort-slider-track">
      <Slider.Fill className="effort-slider-fill">
        {energized && <span className="effort-slider-sparks" aria-hidden="true">
          {Array.from({ length: 12 }, (_, index) => <i key={index} />)}
        </span>}
      </Slider.Fill>
      <span className="effort-slider-marks" aria-hidden="true">{labels.map((label, index) => <span key={label + index} style={{ left: `${index / Math.max(1, labels.length - 1) * 100}%` }} data-filled={index <= value || undefined} />)}</span>
      <Slider.Thumb className="effort-slider-thumb" inputRef={inputRef} />
    </Slider.Track>
  </Slider>
}
