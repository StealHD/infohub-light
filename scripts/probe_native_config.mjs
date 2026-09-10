// Offline validation against the installed OpenClaw schema; never starts a Gateway.
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

async function main() {
  let input = ''
  for await (const chunk of process.stdin) {
    input += chunk
    if (input.length > 2 * 1024 * 1024) throw new Error('Oversized probe')
  }
  const { packageRoot, configs } = JSON.parse(input)
  const dist = join(packageRoot, 'dist')
  const candidates = []
  for (const name of await readdir(dist)) {
    if (!/^zod-schema-[\w-]+\.m?js$/.test(name)) continue
    const source = await readFile(join(dist, name), 'utf8')
    const exports = source.match(/export \{[^}]+\}/g)?.join(' ') ?? ''
    const alias = exports.match(/\bOpenClawSchema as (\w+)\b/)?.[1]
    if (alias) candidates.push({ name, alias })
  }
  if (candidates.length !== 1 || !Array.isArray(configs) || !configs.length) throw new Error('Unsupported schema')
  const { name, alias } = candidates[0]
  const schema = (await import(pathToFileURL(join(dist, name)).href))[alias]
  const results = configs.map(config => schema.safeParse(config))
  const failures = results.flatMap((result, index) => result.success ? [] :
    result.error.issues.map(issue => ({ index, path: issue.path, code: issue.code })))
  const { version } = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'))
  process.stdout.write(JSON.stringify({ version, valid: failures.length === 0, failures }))
  if (failures.length) process.exitCode = 1
}

main().catch(() => { process.exitCode = 1 })
