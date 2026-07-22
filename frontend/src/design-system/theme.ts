export const designSystemTheme = {
  root: {
    colorScheme: 'system',
    name: 'graphite-purple',
  },
  colors: {
    canvas: 'var(--background)',
    surface: 'var(--surface)',
    surfaceRaised: 'var(--surface-secondary)',
    surfaceOverlay: 'var(--surface-tertiary)',
    accent: 'var(--accent)',
  },
  radii: {
    panel: 'var(--inteliscope-radius-panel)',
    card: 'var(--inteliscope-radius-card)',
    control: 'var(--inteliscope-radius-control)',
    compact: 'var(--inteliscope-radius-compact)',
  },
  motion: {
    fast: 'var(--inteliscope-motion-fast)',
    standard: 'var(--inteliscope-motion-standard)',
    deliberate: 'var(--inteliscope-motion-deliberate)',
  },
  widths: {
    reading: 'var(--inteliscope-width-reading)',
    admin: 'var(--inteliscope-width-admin)',
    auth: 'var(--inteliscope-width-auth)',
  },
} as const
