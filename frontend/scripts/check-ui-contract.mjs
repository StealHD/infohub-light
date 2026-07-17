import { readFile, readdir } from 'node:fs/promises'
import { extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const controlledRoots = ['src/app', 'src/features/feed', 'src/features/workbench', 'src/features/workbench-heroui']
const sourceExtensions = new Set(['.ts', '.tsx'])
const violations = []

async function sourceFiles(directory) {
  const entries = await readdir(join(root, directory), { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) files.push(...await sourceFiles(path))
    else if (sourceExtensions.has(extname(entry.name)) && !entry.name.includes('.test.')) files.push(path)
  }
  return files
}

for (const file of await sourceFiles('src')) {
  const source = await readFile(join(root, file), 'utf8')
  const isHeroWorkbench = file.startsWith('src/features/workbench-heroui/')
  if (!isHeroWorkbench && /(?:from|import\s*)\s*['"]@heroui\//.test(source)) {
    violations.push(`${relative(root, join(root, file))}: HeroUI 只能用于独立工作台原型边界`)
  }
  if (isHeroWorkbench && /from\s+['"]\.\.\/\.\.\/ui(?:\/[^'"]*)?['"]/.test(source)) {
    violations.push(`${relative(root, join(root, file))}: HeroUI 原型不得引入 MUI 内部导出层`)
  }
}

const mainSource = await readFile(join(root, 'src/main.tsx'), 'utf8')
if (!/import\.meta\.env\.DEV[\s\S]*workbench-heroui/.test(mainSource)) {
  violations.push('src/main.tsx: HeroUI 原型必须由 import.meta.env.DEV 条件动态导入')
}

for (const directory of controlledRoots) {
  for (const file of await sourceFiles(directory)) {
    const source = await readFile(join(root, file), 'utf8')
    const checks = [
      [/(?:from|import\s*)\s*['"]@mui\/material(?:\/[^'"]+)?['"]/, '受控 MUI 组件必须从 src/ui 引入'],
      [/(?:from|import\s*)\s*['"]@mui\/icons-material(?:\/[^'"]+)?['"]/, '图标必须从 src/ui/icons 引入'],
      [/(?:from|import\s*)\s*['"]@emotion\/[^'"]+['"]/, '业务层不得直接引入 Emotion'],
      [/from\s+['"].*\.module\.css['"]/, 'Shell 与 Feed 不得新增或依赖页面级 CSS Modules'],
      [/(?:#[0-9a-f]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\()/i, '业务页面不得定义原始颜色值'],
      [/\b(?:borderRadius|boxShadow)\s*:\s*(?:['"]?\d|['"][^'"]+)/, '圆角和阴影必须来自内部 UI 主题语义'],
    ]
    for (const [pattern, message] of checks) {
      if (pattern.test(source)) violations.push(`${relative(root, join(root, file))}: ${message}`)
    }
  }
}

if (violations.length) {
  console.error(`UI contract check failed:\n${violations.map((value) => `- ${value}`).join('\n')}`)
  process.exitCode = 1
} else {
  console.log('UI contract check passed.')
}
