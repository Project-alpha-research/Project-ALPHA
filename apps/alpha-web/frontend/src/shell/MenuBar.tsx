// Menu bar (spec 2026-09-01 §4.2 item 2): eleven menus, keyboard operable — ArrowLeft/Right move
// between menus (and switch an open one), Enter/Space/ArrowDown open, ArrowUp/Down walk the items,
// Escape closes and returns focus. Only menus with items are shown.

import { useCallback, useEffect, useRef, useState } from 'react'

import type { OpenDocument } from './mdiModel'
import { commandHome, menuBar, visibleMenus, type MenuItem, type MenuName, type ShellMenuState } from './menuModel'
import type { DockId, WindowId } from './profiles'

interface Props {
  tasks?: readonly { title: string; page: string; pane: string }[]
  onTask?: (page: string, pane: string) => void
  open: readonly OpenDocument[]
  active: string | null
  available: readonly { id: WindowId; title: string }[]
  shell: ShellMenuState
  onOpenWindow: (id: WindowId) => void
  onActivate: (key: string) => void
  onPalette: () => void
  onSettings: () => void
  onIndicators: () => void
  onNewChart: () => void
  onTile: () => void
  onToggleDock: (id: DockId) => void
}

/** A shell item with a `checked` flag renders as a checkbox (Window › Tile charts). */
function checkedOf(item: MenuItem): boolean | undefined {
  return item.kind === 'shell' ? item.checked : undefined
}

export function MenuBar({
  tasks = [], onTask,
  open,
  active,
  available,
  shell,
  onOpenWindow,
  onActivate,
  onPalette,
  onSettings,
  onIndicators,
  onNewChart,
  onTile,
  onToggleDock,
}: Props) {
  const [openMenu, setOpenMenu] = useState<MenuName | null>(null)
  const bar = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!openMenu) return
    const onDown = (event: MouseEvent) => {
      if (bar.current && !bar.current.contains(event.target as Node)) setOpenMenu(null)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [openMenu])

  const menus = menuBar(open, active, available, shell)
  const shown = visibleMenus(menus)

  const focusMenu = useCallback((name: MenuName) => {
    bar.current?.querySelector<HTMLButtonElement>(`[data-menu="${name}"]`)?.focus()
  }, [])

  const select = (item: MenuItem) => {
    setOpenMenu(null)
    if (item.kind === 'command') {
      const home = commandHome(item.id)
      if (home?.kind === 'window') onOpenWindow(home.id)
      else if (home?.kind === 'dock') onToggleDock(home.id)
    }
    else if (item.kind === 'document') onActivate(item.key)
    else if (item.kind === 'open') onOpenWindow(item.window)
    else if (item.kind === 'dock') onToggleDock(item.id)
    else if (item.id === 'palette') onPalette()
    else if (item.id === 'indicators') onIndicators()
    else if (item.id === 'new-chart') onNewChart()
    else if (item.id === 'tile') onTile()
    else onSettings()
  }

  const onTopKey = (name: MenuName, index: number) => (event: React.KeyboardEvent) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (step) {
      event.preventDefault()
      const next = shown[(index + step + shown.length) % shown.length]
      focusMenu(next)
      if (openMenu) setOpenMenu(next)
    } else if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      setOpenMenu(name)
      window.setTimeout(() => {
        bar.current?.querySelector<HTMLButtonElement>(`[data-menu-of="${name}"] .menu-item`)?.focus()
      }, 0)
    } else if (event.key === 'Escape') {
      setOpenMenu(null)
    }
  }

  const onItemKey = (name: MenuName) => (event: React.KeyboardEvent<HTMLButtonElement>) => {
    const items = [
      ...(bar.current?.querySelectorAll<HTMLButtonElement>(`[data-menu-of="${name}"] .menu-item`) ?? []),
    ]
    const index = items.indexOf(event.currentTarget)
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      items[(index + step + items.length) % items.length]?.focus()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      setOpenMenu(null)
      focusMenu(name)
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault()
      const at = shown.indexOf(name)
      const next = shown[(at + (event.key === 'ArrowRight' ? 1 : -1) + shown.length) % shown.length]
      setOpenMenu(next)
      focusMenu(next)
    }
  }

  return (
    <div className="menubar" role="menubar" aria-label="Terminal menu" ref={bar}>
      {shown.map((name, index) => (
        <div key={name} className="menu">
          <button
            type="button"
            role="menuitem"
            data-menu={name}
            className={`menu-title${openMenu === name ? ' open' : ''}`}
            aria-haspopup="menu"
            aria-expanded={openMenu === name}
            onClick={() => setOpenMenu((current) => (current === name ? null : name))}
            onMouseEnter={() => openMenu && setOpenMenu(name)}
            onKeyDown={onTopKey(name, index)}
          >
            {name}
          </button>
          {openMenu === name ? (
            <div className="menu-pop" role="menu" aria-label={name} data-menu-of={name}>
              {menus[name].map((item) => (
                  <button
                    key={`${item.kind}:${'id' in item ? item.id : 'key' in item ? item.key : item.window}`}
                    type="button"
                    role={item.kind === 'dock' || checkedOf(item) !== undefined ? 'menuitemcheckbox' : 'menuitem'}
                    aria-checked={item.kind === 'dock' ? item.open : checkedOf(item)}
                    className={`menu-item${item.kind === 'document' && item.active ? ' active' : ''}${item.kind === 'dock' || checkedOf(item) !== undefined ? ' menu-check' : ''}`}
                    onClick={() => select(item)}
                    onKeyDown={onItemKey(name)}
                  >
                    {item.kind === 'dock' || checkedOf(item) !== undefined ? (
                      <span className="menu-mark" aria-hidden="true">
                        {(item.kind === 'dock' ? item.open : checkedOf(item)) ? '✓' : ''}
                      </span>
                    ) : null}
                    {item.kind === 'command' ? <span className="mono">alpha {item.label}</span> : item.label}
                  </button>
                ))}
              {name === 'View' ? tasks.map(task => <button key={task.pane} role="menuitem" className="menu-item" onKeyDown={onItemKey(name)} onClick={() => { setOpenMenu(null); onTask?.(task.page, task.pane) }}>{task.title}</button>) : null}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
}
