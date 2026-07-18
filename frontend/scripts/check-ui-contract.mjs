import { readFile, readdir } from 'node:fs/promises'
import { extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const sourceExtensions = new Set(['.ts', '.tsx', '.css'])

function sourceViolations(file, source) {
  const violations = []
  const isDesignSystem = file.startsWith('src/design-system/')
  const isHeroWorkbench = file.startsWith('src/features/workbench-heroui/')
  const isBusinessSource = file.startsWith('src/app/') || file.startsWith('src/features/')
  const importsHeroUi = /\b(?:from\s*|import\s*(?:\(\s*)?)['"`]@heroui\//.test(source)
  if (importsHeroUi && !isDesignSystem && !isHeroWorkbench) {
    violations.push(`${file}: HeroUI 必须通过 src/design-system 引入`)
  }
  if (/['"`]@(?:mui|emotion)\//.test(source)) {
    violations.push(`${file}: MUI/Emotion 已从源码移除`)
  }
  if (isBusinessSource && /\bDesignSystemProvider\b/.test(source)) {
    violations.push(`${file}: DesignSystemProvider 只能由 AppBootstrap 挂载`)
  }
  if (/\/__preview\/workbench-live|\/__preview\/workbench(?!-heroui)|切换到\s*MUI|from\s+['"][^'"]*(?:\/ui|\/workbench\/WorkbenchPreview)['"]/.test(source)) {
    violations.push(`${file}: 已删除的验收路由或 MUI 原型文案`)
  }
  if (isBusinessSource && !isHeroWorkbench) {
    const arbitraryTypographyUtility = /(?:^|[^A-Za-z0-9_-])(?:text-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl|8xl|9xl|\[[^\]]+\])|font-(?:thin|extralight|light|normal|medium|semibold|bold|extrabold|black|\[[^\]]+\])|leading-(?:none|tight|snug|normal|relaxed|loose|[3-9]|10|\[[^\]]+\])|tracking-(?:tighter|tight|normal|wide|wider|widest|\[[^\]]+\]))(?=$|[^A-Za-z0-9_[\]-])/
    const checks = [
      [/\bimport\s*(?:\(\s*)?(?:[^'"`\n]+\s+from\s+)?['"`][^'"`]*\.module\.css['"`]\s*\)?/, 'Shell 与业务页不得使用页面级 CSS Modules'],
      [/(?:#[0-9a-f]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\(|\b(?:oklch|oklab|lab|lch)\s*\(|\bcolor\s*\(\s*display-p3\b)/i, '业务页面不得定义原始颜色值'],
      [/\b(?:borderRadius|boxShadow|transitionDuration|animationDuration)\s*:\s*(?:['"]?\d|['"][^'"]+)|\b(?:border-radius|box-shadow|transition-duration|animation-duration)\s*:/, '视觉常量必须来自设计系统主题'],
      [arbitraryTypographyUtility, '业务文字必须使用设计系统语义排版'],
    ]
    for (const [pattern, message] of checks) if (pattern.test(source)) violations.push(`${file}: ${message}`)
  }
  return violations
}

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

async function checkWorkspace() {
  const violations = []

  for (const file of await sourceFiles('src')) {
    const source = await readFile(join(root, file), 'utf8')
    violations.push(...sourceViolations(file, source))
  }

  const mainSource = await readFile(join(root, 'src/main.tsx'), 'utf8')
  if (!/import\.meta\.env\.DEV[\s\S]*workbench-heroui/.test(mainSource)) {
    violations.push('src/main.tsx: HeroUI 原型必须由 import.meta.env.DEV 条件动态导入')
  }

  const manifest = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'))
  const dependencies = Object.keys({ ...manifest.dependencies, ...manifest.devDependencies })
  for (const name of dependencies.filter((value) => value.startsWith('@mui/') || value.startsWith('@emotion/'))) {
    violations.push(`package.json: 已删除的 UI 依赖 ${name}`)
  }

  if (violations.length) {
    console.error(`UI contract check failed:\n${violations.map((value) => `- ${value}`).join('\n')}`)
    process.exitCode = 1
  } else {
    console.log('UI contract check passed.')
  }
}

if (process.argv[2] === '--check-source' || process.argv[2] === '--check-heroui-source') {
  const file = process.argv[3] ?? ''
  let source = ''
  process.stdin.setEncoding('utf8')
  for await (const chunk of process.stdin) source += chunk
  const violations = sourceViolations(file, source)
  if (violations.length) {
    console.error(violations.join('\n'))
    process.exitCode = 1
  }
} else {
  await checkWorkspace()
}
