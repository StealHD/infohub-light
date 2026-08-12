import { readFile, readdir } from 'node:fs/promises'
import { extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { brotliCompressSync, constants as zlibConstants } from 'node:zlib'

const root = fileURLToPath(new URL('..', import.meta.url))
const buildRootOption = process.argv.indexOf('--build-root')
const buildRoot = buildRootOption >= 0
  ? resolve(process.argv[buildRootOption + 1] ?? '')
  : join(root, '../src/ui/service_static')
const searchableExtensions = new Set(['.html', '.js', '.css', '.map'])
const forbidden = [
  'inteliscope-fixed-preview-fixture-v1',
  '/__preview/workbench-heroui',
  'hero-workbench',
  '正在准备 HeroUI 工作台预览',
  '/__preview/workbench-live',
  '/__preview/workbench',
  '@mui/',
  '@emotion/',
  '切换到 MUI 版',
]
const forbiddenPatterns = [
  { pattern: /\bMui(?:[A-Z][A-Za-z0-9]*)?-[A-Za-z0-9-]+\b/, label: 'MUI class marker' },
]
const initialJavaScriptBrotliBudget = 240 * 1024
const requiredLazyChunks = [
  'HeroAgentsPage',
  'HeroChangelogPage',
  'HeroLoginPage',
  'HeroManualPage',
  'OpenClawConversation',
  'HeroSubscriptionsPage',
  'HeroUsersPage',
  'SettingsActorOpsPage',
  'SettingsAIPage',
  'SettingsAppearancePage',
  'SettingsFetchingPage',
  'SettingsIgnoredPage',
  'SettingsLayout',
  'SettingsNotificationsPage',
  'SettingsOverviewPage',
  'SettingsSecretsPage',
  'SettingsStoragePage',
]
const violations = []

async function files(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const result = []
  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) result.push(...await files(path))
    else if (searchableExtensions.has(extname(entry.name))) result.push(path)
  }
  return result
}

const buildFiles = await files(buildRoot)
for (const file of buildFiles) {
  const source = await readFile(file, 'utf8')
  for (const marker of forbidden) {
    if (source.includes(marker)) violations.push(`${file}: 包含开发专用 HeroUI 标记 ${marker}`)
  }
  for (const { pattern, label } of forbiddenPatterns) {
    if (pattern.test(source)) violations.push(`${file}: 包含已删除的 ${label}`)
  }
}

const indexPath = join(buildRoot, 'index.html')
let initialJavaScriptBrotliBytes = null
if (buildFiles.includes(indexPath)) {
  const indexSource = await readFile(indexPath, 'utf8')
  const initialJavaScriptReferences = [
    ...new Set(
      [...indexSource.matchAll(/(?:src|href)="(\/assets\/[^"]+\.js)"/g)]
        .map((match) => match[1]),
    ),
  ]
  initialJavaScriptBrotliBytes = 0
  for (const reference of initialJavaScriptReferences) {
    const source = await readFile(join(buildRoot, reference))
    initialJavaScriptBrotliBytes += brotliCompressSync(source, {
      params: {
        [zlibConstants.BROTLI_PARAM_QUALITY]: 11,
      },
    }).byteLength
  }
  if (initialJavaScriptBrotliBytes > initialJavaScriptBrotliBudget) {
    violations.push(
      `${indexPath}: 首屏 JavaScript Brotli 体积 ${initialJavaScriptBrotliBytes} bytes 超过 ${initialJavaScriptBrotliBudget} bytes`,
    )
  }

  const builtNames = buildFiles.map((file) => file.slice(buildRoot.length + 1))
  for (const chunkName of requiredLazyChunks) {
    if (!builtNames.some((name) => name.startsWith(`assets/${chunkName}-`) && name.endsWith('.js'))) {
      violations.push(`${buildRoot}: 缺少按需加载独立分包 ${chunkName}`)
    }
  }
}

if (violations.length) {
  console.error(`Production UI artifact check failed:\n${violations.map((value) => `- ${value}`).join('\n')}`)
  process.exitCode = 1
} else {
  const sizeSummary = initialJavaScriptBrotliBytes === null
    ? ''
    : ` Initial JavaScript Brotli: ${initialJavaScriptBrotliBytes} bytes.`
  console.log(`Production UI artifact check passed.${sizeSummary}`)
}
