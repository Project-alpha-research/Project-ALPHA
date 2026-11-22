import './fonts.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import './theme.generated.css'
import './index.css'
import './workflow.css'
import './v2/tokens.css'
import './v2/desk.css'
import './v2/pages.css'
import { initSettings } from './state/settings'
import { DeskApp } from './v2/DeskApp'
import { isLegacyHash } from './v2/deskModel'

initSettings()

// The desk is the default app. The old shell stays reachable at `#legacy` (and its own `#page=`
// links) until later slices replace it.
const legacy = isLegacyHash(window.location.hash) || window.location.pathname === '/owner-auth/enroll'
if (!legacy) {
  document.documentElement.dataset.desk = 'v2'
  document.documentElement.dataset.theme = 'dark'
}

const root = document.getElementById('root')
if (!root) throw new Error('missing #root')
createRoot(root).render(
  <StrictMode>
    {legacy ? <App /> : <DeskApp />}
  </StrictMode>,
)

// Moving between the desk and the old shell needs a fresh page: each owns the whole document.
window.addEventListener('hashchange', () => {
  if (isLegacyHash(window.location.hash) !== legacy) window.location.reload()
})
