// Read-only probe of the installed OpenClaw transport implementation, not a model run.
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

async function main() {
  let input = ''
  for await (const chunk of process.stdin) {
    input += chunk
    if (input.length > 32768) throw new Error('Oversized probe')
  }
  const { packageRoot, server, config, requiredTools } = JSON.parse(input)
  const dist = join(packageRoot, 'dist')
  const names = (await readdir(dist)).filter(name => /^(mcp-transport|mcp-client-lifecycle)-[\w-]+\.m?js$/.test(name))
  const symbols = ['resolveMcpTransport', 'connectMcpClient', 'disposeMcpClient']
  const candidates = symbols.map(() => [])
  for (const name of names) {
    const source = await readFile(join(dist, name), 'utf8')
    const exported = source.match(/export \{[^}]+\}/g)?.join(' ') ?? ''
    symbols.forEach((symbol, index) => {
      const alias = exported.match(new RegExp(`\\b${symbol} as (\\w+)\\b`))?.[1]
      if (alias) candidates[index].push({ name, alias })
    })
  }
  if (candidates.some(matches => matches.length !== 1)) throw new Error('Unsupported native module layout')
  const [resolve, connect, dispose] = await Promise.all(candidates.map(async ([{ name, alias }]) =>
    (await import(pathToFileURL(join(dist, name)).href))[alias]))
  const { Client } = await import(pathToFileURL(join(packageRoot,
    'node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js')).href)
  const resolved = resolve(server, config)
  if (resolved?.transportType !== 'streamable-http') throw new Error('Unsupported resolved transport')
  const client = new Client({ name: 'inteliscope-install-verification', version: '1' })
  try {
    await connect({ client, transport: resolved.transport, timeoutMs: 15000 })
    const catalog = await client.listTools({}, { timeout: 15000 })
    if (!requiredTools.every(name => catalog.tools.some(tool => tool.name === name && tool.annotations?.readOnlyHint === true))) {
      throw new Error('Incomplete personal tool catalog')
    }
    const result = await client.callTool({ name: 'list_subscriptions', arguments: {} }, undefined, { timeout: 15000 })
    if (result.isError) throw new Error('Personal read failed')
    process.stdout.write(JSON.stringify({ native_transport: 'streamable-http', personal_tools: true }))
  } finally {
    await dispose({ ...resolved, client })
  }
}

main().catch(() => { process.exitCode = 1 })
