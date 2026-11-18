// Shared technical-chart chrome for every BokehJS plot that is not the price stack (recorded
// equity/drawdown/Sharpe series, histograms, QQ): no toolbar, right-hand value axis, StockCharts
// fonts, 1px grid and border, light plot surface. Same tokens as the price stack.

import type { HoverTool } from '@bokeh/bokehjs/build/js/lib/models/tools/inspectors/hover_tool'
import type { Figure } from '@bokeh/bokehjs/build/js/lib/api/figure'
import type { TechnicalStyle } from './technicalTokens'

export function technicalFigureAttrs(style: TechnicalStyle) {
  return {
    toolbar_location: null,
    y_axis_location: 'right' as const,
    background_fill_color: style.plot,
    border_fill_color: style.canvas,
    outline_line_color: style.border,
    outline_line_width: 1,
    min_border: 6,
    // Room for the right-axis value tag, as in the price stack.
    min_border_right: 64,
  }
}

export function styleTechnicalAxes(plot: Figure, style: TechnicalStyle): void {
  plot.axis.major_label_text_font = style.font
  plot.axis.major_label_text_font_size = `${style.fontSize}px`
  plot.axis.major_label_text_color = style.text
  plot.axis.axis_label_text_font = style.font
  plot.axis.axis_label_text_font_size = `${style.fontSize}px`
  plot.axis.axis_label_text_font_style = 'normal'
  plot.axis.axis_label_text_color = style.text
  plot.axis.axis_line_color = null
  plot.axis.major_tick_line_color = style.border
  plot.axis.major_tick_in = 0
  plot.axis.major_tick_out = 3
  plot.axis.minor_tick_line_color = null
  plot.grid.grid_line_color = style.grid
  plot.grid.grid_line_width = 1
}

/** Restyle a mounted plot without disturbing the ranges or data sources. */
export function recolorPlot(plot: Figure, style: TechnicalStyle) {
  plot.background_fill_color = style.plot
  plot.border_fill_color = style.canvas
  plot.outline_line_color = style.border
  styleTechnicalAxes(plot, style)
  plot.toolbar.styles = { backgroundColor: style.header, color: style.text, opacity: '1' }
}

/** Bokeh attaches hover popovers to document.body, outside the chart's CSS scope. */
export function styleHover(tool: HoverTool, style: TechnicalStyle) {
  const view = tool.document?.views_manager?.find_one(tool)
  if (!view) return
  for (const tooltip of view.ttmodels.values()) {
    tooltip.stylesheets = [`:host {
      --tooltip-color: ${style.canvas}; --tooltip-text: ${style.text};
      --tooltip-border: ${style.border}; --tooltip-arrow-color: ${style.border};
      --tooltip-arrow-inner-color: ${style.canvas}; font: ${style.fontSize}px ${style.font}; opacity: 1;
    }
    .bk-tooltip-row-label { color: ${style.muted}; }`]
  }
}

/** Box style of a right-axis value tag (StockCharts' current-value box), centred on `y`. */
export function tagStyle(style: TechnicalStyle, left: number, y: number, color: string, bold = false): Partial<CSSStyleDeclaration> {
  return { position: 'absolute', left: `${left}px`, top: `${y - 6}px`, lineHeight: '1.2', padding: '0 2px', background: style.plot, border: `1px solid ${color}`, color, font: `${bold ? 'bold ' : ''}${style.fontSize}px ${style.font}`, whiteSpace: 'nowrap', pointerEvents: 'none' }
}
