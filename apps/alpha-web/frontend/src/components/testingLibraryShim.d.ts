// Ambient types for the local, Node-only stand-in for `@testing-library/react`
// that serves component tests offline (see src/components/node_modules).
//
// The package is not installed and the shell has no network, so the shim ships
// JavaScript only. This declaration gives TypeScript the types for the locked
// component tests that import it, without changing the shim's runtime.
declare module '@testing-library/react' {
  export interface RenderResult {
    container: Element
  }

  export function render(ui: unknown): RenderResult

  export const screen: {
    queryAllByRole(role: string): HTMLElement[]
    getAllByRole(role: string): HTMLElement[]
  }

  export const fireEvent: {
    click(element: Element | null): boolean
  }

  const testingLibrary: {
    render: typeof render
    screen: typeof screen
    fireEvent: typeof fireEvent
  }
  export default testingLibrary
}
