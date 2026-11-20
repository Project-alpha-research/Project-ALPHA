import { useLayoutEffect, useRef, useState } from 'react'

/** Width of the box the chart sits in, kept in step with the window. 560 until measured. Never wider than the box. */
export function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(560)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () => setWidth(Math.max(240, Math.min(760, Math.floor(element.clientWidth) || 560)))
    measure()
    const watcher = new ResizeObserver(measure)
    watcher.observe(element)
    return () => watcher.disconnect()
  }, [])
  return [ref, width]
}
