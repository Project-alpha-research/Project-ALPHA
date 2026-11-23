// Test-only mount of the actual risk consumer; no metric substitute.
import React from 'react'
import { createRoot } from 'react-dom/client'

import '../src/index.css'
import { setLinked } from '../src/context/linked'
import { Risk } from '../src/panels/rundetail/Risk'

const query = new URLSearchParams(location.search)
let runId = query.get('run') ?? ''
const root = createRoot(document.getElementById('risk-root')!)
function render() {
  setLinked({ runId })
  root.render(<Risk manifest={{}} runId={runId} />)
}
Object.assign(window, { c04SetRun: (value: string) => { runId = value; render() } })
render()
