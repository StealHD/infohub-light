import { readFile, readdir } from 'node:fs/promises'
import { extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const buildRoot = join(root, '../src/ui/service_static')
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
  { pattern: /\bMui[A-Z][A-Za-z0-9]*-[A-Za-z0-9-]+\b/, label: 'MUI class marker' },
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

for (const file of await files(buildRoot)) {
  const source = await readFile(file, 'utf8')
  for (const marker of forbidden) {
    if (source.includes(marker)) violations.push(`${file}: 包含开发专用 HeroUI 标记 ${marker}`)
  }
  for (const { pattern, label } of forbiddenPatterns) {
    if (pattern.test(source)) violations.push(`${file}: 包含已删除的 ${label}`)
  }
}

if (violations.length) {
  console.error(`Production UI artifact check failed:\n${violations.map((value) => `- ${value}`).join('\n')}`)
  process.exitCode = 1
} else {
  console.log('Production UI artifact check passed.')
}
