import { expect, test } from '@playwright/test'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'node:path'
import { build, type Rollup } from 'vite'

let compiledThemeCss = ''

test.beforeAll(async () => {
  const result = await build({
    configFile: false,
    logLevel: 'silent',
    plugins: [tailwindcss()],
    build: {
      write: false,
      rollupOptions: { input: resolve(process.cwd(), 'src/design-system/theme.css') },
    },
  })
  const output = (Array.isArray(result) ? result : [result])
    .flatMap((buildResult) => buildResult.output)
  const css = output.find((entry): entry is Rollup.OutputAsset => entry.type === 'asset' && entry.fileName.endsWith('.css'))
  if (!css) throw new Error('Compiled design-system CSS asset was not emitted')
  compiledThemeCss = String(css.source)
})

async function mountContractSurface(page: import('@playwright/test').Page) {
  await page.setContent(`
    <style>${compiledThemeCss}</style>
    <main class="inteliscope-design-system" data-theme="dark" data-inteliscope-theme="graphite-purple">
      <div class="tabs__list-container" data-testid="tabs-radius">
        <button class="tabs__list-container__scroll-next" data-testid="tabs-scroll-radius"></button>
      </div>
      <div class="table-root table-root--primary" data-testid="table-radius"></div>
      <button class="button button--primary" data-testid="motion-button">保存</button>
      <button class="modal__trigger" data-testid="motion-modal">打开弹窗</button>
      <div class="tooltip" data-entering="true" data-testid="motion-tooltip">说明</div>
    </main>
  `)
}

function milliseconds(value: string) {
  return value.split(',').map((duration) => {
    const normalized = duration.trim()
    return normalized.endsWith('ms') ? Number.parseFloat(normalized) : Number.parseFloat(normalized) * 1000
  })
}

test('compiled HeroUI Tabs and Table radii stay on the approved scale', async ({ page }) => {
  await mountContractSurface(page)

  await expect(page.getByTestId('tabs-radius')).toHaveCSS('border-radius', '14px')
  await expect(page.getByTestId('table-radius')).toHaveCSS('border-radius', '16px')
  await expect(page.getByTestId('tabs-scroll-radius')).toHaveCSS('border-radius', '8px')
})

test('compiled component motion stays within 120–220ms and honors Reduced Motion', async ({ page }) => {
  await mountContractSurface(page)

  const normalDurations = await page.locator('[data-testid^="motion-"]').evaluateAll((elements) => elements.flatMap((element) => {
    const style = getComputedStyle(element)
    return [style.transitionDuration, style.animationDuration]
  }))
  const activeNormalDurations = normalDurations.flatMap(milliseconds).filter((duration) => duration > 0)
  expect(activeNormalDurations.length).toBeGreaterThanOrEqual(6)
  expect(activeNormalDurations.every((duration) => duration >= 120 && duration <= 220)).toBe(true)
  expect(compiledThemeCss).toMatch(/::view-transition-new\(\.toast-bottom\):only-child[^}]*animation-duration:var\(--inteliscope-motion-deliberate\)!important/)

  await page.emulateMedia({ reducedMotion: 'reduce' })
  const reducedDurations = await page.locator('[data-testid^="motion-"]').evaluateAll((elements) => elements.flatMap((element) => {
    const style = getComputedStyle(element)
    return [style.transitionDuration, style.animationDuration]
  }))
  expect(reducedDurations.flatMap(milliseconds).every((duration) => duration <= 1)).toBe(true)
})
