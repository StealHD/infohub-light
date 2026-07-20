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
  expect(activeNormalDurations.length).toBeGreaterThanOrEqual(3)
  expect(activeNormalDurations.every((duration) => duration >= 120 && duration <= 220)).toBe(true)
  expect(compiledThemeCss).toMatch(/::view-transition-new\(\.toast-bottom\):only-child[^}]*animation-duration:var\(--inteliscope-motion-deliberate\)!important/)

  await page.emulateMedia({ reducedMotion: 'reduce' })
  const reducedMotion = await page.locator('[data-testid^="motion-"]').evaluateAll((elements) => elements.map((element) => {
    const style = getComputedStyle(element)
    return {
      animationName: style.animationName,
      transitionProperty: style.transitionProperty,
    }
  }))
  expect(reducedMotion.every(({ animationName, transitionProperty }) => (
    animationName === 'none' && transitionProperty === 'none'
  ))).toBe(true)
})

test('real Modal and Tooltip portals inherit the theme and release the document root on unmount', async ({ page }) => {
  await page.goto('/e2e/fixtures/design-system-portal.html')

  const modal = page.locator('[data-slot="modal-dialog"]')
  const modalContainer = page.locator('[data-slot="modal-container"]')
  const tooltip = page.getByText('真实 Portal 提示')
  await expect(modal).toBeVisible()
  await expect(tooltip).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.locator('html')).toHaveAttribute('data-inteliscope-theme', 'graphite-purple')
  await expect(page.locator('html')).toHaveClass(/inteliscope-design-system/)
  await expect(modal).toHaveCSS('border-radius', '16px')
  await expect(tooltip).toHaveCSS('border-radius', '10px')
  const themedForeground = await page.getByTestId('static-surface').evaluate((element) => getComputedStyle(element).color)
  await expect(modal).toHaveCSS('color', themedForeground)
  await expect(tooltip).toHaveCSS('color', themedForeground)

  const portalDurations = await Promise.all([
    modalContainer.evaluate((element) => {
      element.setAttribute('data-entering', 'true')
      const style = getComputedStyle(element)
      return { animationName: style.animationName, duration: style.animationDuration }
    }),
    tooltip.evaluate((element) => {
      element.setAttribute('data-exiting', 'true')
      const style = getComputedStyle(element)
      return { animationName: style.animationName, duration: style.animationDuration }
    }),
  ])
  expect(portalDurations.every(({ animationName }) => animationName !== 'none')).toBe(true)
  expect(portalDurations.flatMap(({ duration }) => milliseconds(duration)).every((duration) => duration >= 120 && duration <= 220)).toBe(true)

  await page.evaluate(() => window.unmountDesignSystemFixture())
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'legacy')
  await expect(page.locator('html')).toHaveAttribute('data-inteliscope-theme', 'legacy-theme')
  await expect(page.locator('html')).toHaveClass('legacy-root')
  await expect(page.locator('[data-slot="modal-dialog"]')).toHaveCount(0)
  await expect(page.getByText('真实 Portal 提示')).toHaveCount(0)
})

test('static content stays motionless while Skeleton and Spinner keep continuous cadence', async ({ page }) => {
  await page.goto('/e2e/fixtures/design-system-portal.html')

  const staticMotion = await page.getByTestId('static-surface').evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      animationDuration: style.animationDuration,
      animationName: style.animationName,
      transitionDuration: style.transitionDuration,
      transitionProperty: style.transitionProperty,
    }
  })
  expect(staticMotion).toEqual({
    animationDuration: '0s',
    animationName: 'none',
    transitionDuration: '0s',
    transitionProperty: 'all',
  })

  for (const testId of ['continuous-skeleton', 'continuous-spinner']) {
    const continuousMotion = await page.getByTestId(testId).evaluate((element) => {
      const style = getComputedStyle(element)
      return { animationDuration: style.animationDuration, animationName: style.animationName }
    })
    expect(continuousMotion.animationName).not.toBe('none')
    expect(milliseconds(continuousMotion.animationDuration)[0]).toBeGreaterThan(220)
  }

  const finiteButton = await page.getByTestId('finite-button').evaluate((element) => {
    const style = getComputedStyle(element)
    return { duration: style.transitionDuration, property: style.transitionProperty }
  })
  expect(finiteButton.property).toContain('transform')
  expect(milliseconds(finiteButton.duration).every((duration) => duration >= 120 && duration <= 220)).toBe(true)
})

test('real portaled motion honors Reduced Motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/e2e/fixtures/design-system-portal.html')

  const modalContainer = page.locator('[data-slot="modal-container"]')
  const tooltip = page.getByText('真实 Portal 提示')
  for (const [locator, attribute] of [[modalContainer, 'data-entering'], [tooltip, 'data-exiting']] as const) {
    const motion = await locator.evaluate((element, motionAttribute) => {
      element.setAttribute(motionAttribute, 'true')
      const style = getComputedStyle(element)
      return { animationDuration: style.animationDuration, animationName: style.animationName }
    }, attribute)
    expect(motion.animationName).toBe('none')
    expect(milliseconds(motion.animationDuration).every((duration) => duration <= 1)).toBe(true)
  }
})
