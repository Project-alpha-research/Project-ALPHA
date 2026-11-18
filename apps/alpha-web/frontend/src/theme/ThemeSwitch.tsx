import { useTheme } from './themeState'
import { chooseTheme, themeNames } from './themes'

export function ThemeSwitch() {
  const theme = useTheme()
  return <label>Theme<select className="field" value={theme} onChange={event => chooseTheme(event.target.value)}>
    {themeNames.map(name => <option key={name} value={name}>{name[0].toUpperCase() + name.slice(1)}</option>)}
  </select></label>
}
