// Shades the held-back period (the owner's reserved final-check data) on the price pane and names it.

import type {
  IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time, UTCTimestamp,
} from 'lightweight-charts'

export const HELD_BACK_LABEL = 'Held back: not used by tests'

class HeldBackRenderer implements IPrimitivePaneRenderer {
  private readonly from: number
  private readonly fill: string
  private readonly ink: string
  private readonly attached: () => SeriesAttachedParameter<Time> | null

  constructor(from: number, fill: string, ink: string, attached: () => SeriesAttachedParameter<Time> | null) {
    this.from = from; this.fill = fill; this.ink = ink; this.attached = attached
  }

  draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    const attached = this.attached()
    if (!attached) return
    const scale = attached.chart.timeScale()
    const visible = scale.getVisibleRange()
    if (!visible || Number(visible.to) < this.from) return
    const x = Number(visible.from) >= this.from ? 0 : scale.timeToCoordinate(this.from as UTCTimestamp)
    if (x === null) return
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save()
      context.fillStyle = this.fill
      context.fillRect(x, 0, mediaSize.width - x, mediaSize.height)
      context.strokeStyle = this.ink
      context.setLineDash([4, 4])
      context.beginPath(); context.moveTo(x + 0.5, 0); context.lineTo(x + 0.5, mediaSize.height); context.stroke()
      context.setLineDash([])
      context.fillStyle = this.ink
      context.font = '600 12px "Inter Variable", system-ui, sans-serif'
      const width = context.measureText(HELD_BACK_LABEL).width
      if (mediaSize.width - x > width + 16) context.fillText(HELD_BACK_LABEL, x + 8, 18)
      context.restore()
    })
  }
}

class HeldBackView implements IPrimitivePaneView {
  private readonly paneRenderer: HeldBackRenderer
  constructor(paneRenderer: HeldBackRenderer) { this.paneRenderer = paneRenderer }
  zOrder(): 'bottom' { return 'bottom' }
  renderer(): IPrimitivePaneRenderer { return this.paneRenderer }
}

class HeldBack implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private readonly views: readonly IPrimitivePaneView[]
  constructor(from: number, fill: string, ink: string) {
    this.views = [new HeldBackView(new HeldBackRenderer(from, fill, ink, () => this.attachment))]
  }
  attached(param: SeriesAttachedParameter<Time>): void { this.attachment = param }
  detached(): void { this.attachment = null }
  paneViews(): readonly IPrimitivePaneView[] { return this.views }
}

/** `from` is the first held-back bar time (epoch seconds). */
export function heldBackPrimitive(from: number, fill: string, ink: string): ISeriesPrimitive<Time> {
  return new HeldBack(from, fill, ink)
}
