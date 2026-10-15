import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { installAgentApi } from './agentWorkspaceFixtures'

test('real relay blocks inherited model and preserves terminal diagnostics after recovery', async ({ page, context, request, baseURL }, testInfo) => {
  test.setTimeout(120000)
  page.setDefaultTimeout(8000)
  page.setDefaultNavigationTimeout(30000)
  let server: ChildProcess | undefined
  const root = path.resolve('..')
  const fixture = await new Promise<{ url: string; user: string; agent: string; key: string; cookie: string }>((resolve, reject) => {
    server = spawn(path.join(root, '.venv/bin/python'), [path.join(root, 'tests/openclaw_recovery_server.py'), baseURL!], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] })
    let output = ''
    const timer = setTimeout(() => reject(new Error('Service fixture startup timed out')), 15000)
    server.stdout!.on('data', (chunk) => { output += chunk.toString(); if (output.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(output.split('\n')[0])) } })
    server.once('error', reject)
    server.once('exit', (code) => { if (code) { clearTimeout(timer); reject(new Error(`Fixture exited: ${code}`)) } })
  })
  try {
    await installAgentApi(page, true)
    await context.addCookies([{ name: 'horizon_session', value: fixture.cookie, url: fixture.url }])
    await page.addInitScript(({ user, key }) => {
      const marker = 'recovery-fixture-initialized'
      if (!sessionStorage.getItem(marker)) {
        sessionStorage.setItem('infohub-managed-session:' + user, key)
        sessionStorage.setItem(marker, 'true')
      }
      localStorage.setItem('infohub-managed-session:' + user, 'auto')
    }, fixture)
    await page.route('**/api/**', async (route) => {
      const pathname = new URL(route.request().url()).pathname
      let data: unknown
      if (pathname === '/api/auth/status') data = { authenticated: true, user: { id: fixture.user, username: 'owner', role: 'owner', enabled: true } }
      else if (pathname === '/api/me/agent-delegations') data = { enabled: true, connections: [], openclaw_chat: { enabled: true, image_io_enabled: true, default_gateway_url: '/api/me/openclaw/socket', protocol_version: 4 } }
      else if (pathname === '/api/me/agent-connection') data = { state: 'ready', agent_id: fixture.agent, can_connect: true, can_chat: true }
      else return route.fallback()
      return route.fulfill({ json: { ok: true, data } })
    })
    await page.emulateMedia({ colorScheme: testInfo.project.name === 'tablet' ? 'light' : 'dark', reducedMotion: 'reduce' })
    await page.goto(fixture.url + '/agent', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.getByText(/当前会话的模型继承异常/)).toBeVisible({ timeout: 30000 })
    const input = page.getByRole('textbox', { name: '发送给 OpenClaw 的问题' })
    await input.fill('保留草稿并验证选择模型')
    const snapshot = async () => (await (await request.get(fixture.url + '/__fixture')).json())
    expect(Object.keys((await snapshot()).calls)).toHaveLength(0)
    await expect(page.getByTestId('openclaw-timeline').getByText('切换前的上下文', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: /OpenClaw 模型：DeepSeek/ }).click()
    await page.getByRole('button', { name: /选择模型：/ }).click()
    await page.getByRole('option', { name: /DeepSeek/ }).click()
    await expect(page.getByRole('dialog', { name: '模型与思考程度' })).toBeHidden()
    await expect(page.getByText(/当前会话的模型继承异常/)).toHaveCount(0)
    await expect(input).toHaveValue('保留草稿并验证选择模型')
    await expect(page.getByTestId('openclaw-timeline').getByText('切换前的上下文', { exact: true })).toBeVisible()
    expect((await snapshot()).created).toEqual([{ agentId: fixture.agent, model: 'deepseek/flash', parentSessionKey: fixture.key, fork: true }])
    await page.getByRole('button', { name: '发送给 OpenClaw', exact: true }).dblclick()
    await expect(page.getByText('已有部分回复', { exact: true })).toBeVisible({ timeout: 30000 })
    await expect(page.getByText('本次实际模型：deepseek/flash')).toBeVisible()
    await expect(page.getByText(/运行编号：/)).toBeVisible()
    expect(Object.values((await snapshot()).calls)).toMatchObject([{ actual: 'deepseek/flash', deliver: false }])
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByText('已有部分回复', { exact: true })).toBeVisible({ timeout: 30000 })
    await expect(page.getByText('模型额度受限，请稍后手动重试或检查额度。').last()).toBeVisible()
    await expect(page.getByText(/运行编号：/)).toBeVisible()
    expect(Object.keys((await snapshot()).calls)).toHaveLength(1)
    expect(await page.locator('body').innerText()).not.toContain('SECRET')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const axe = await new AxeBuilder({ page }).analyze()
    expect(axe.violations.filter((item) => ['serious', 'critical'].includes(item.impact || ''))).toEqual([])
    await page.screenshot({ path: testInfo.outputPath('model-recovery.png') })
  } finally {
    server?.kill('SIGTERM')
  }
})

test('managed session remains selected after deleting another session and refreshing',async({page},info)=>{
 test.setTimeout(60000)
 await page.emulateMedia({reducedMotion:'reduce'})
 const user='e2e-agent',a='agent:main:a',b='agent:main:b',c='agent:main:created-after-refresh'
 const rows=new Map([[a,{key:a,agentId:'main',displayName:'待删除 A',updatedAt:Date.now(),hasActiveRun:false,archived:false}],[b,{key:b,agentId:'main',displayName:'保留会话 B',updatedAt:Date.now()-1000,hasActiveRun:false,archived:false}]])
 const methods:string[]=[];const errors:string[]=[]
 page.on('pageerror',e=>errors.push(e.name+': '+e.message))
 await installAgentApi(page,true)
 await page.route('**/api/me/agent-delegations',route=>route.fulfill({json:{ok:true,data:{enabled:true,connections:[],openclaw_chat:{enabled:true,image_io_enabled:true,default_gateway_url:'/api/me/openclaw/socket',protocol_version:4}}}}))
 await page.route('**/api/me/agent-connection',route=>route.fulfill({json:{ok:true,data:{state:'ready',agent_id:'main',can_connect:true,can_chat:true}}}))
 await page.addInitScript(({user,a})=>{
  if(!sessionStorage.getItem('diagnostic-seeded')){sessionStorage.setItem('infohub-managed-session:'+user,a);sessionStorage.setItem('diagnostic-seeded','yes')}
  localStorage.setItem('infohub-managed-session:'+user,'auto')
  const gateway = location.origin.replace('http','ws')+'/api/me/openclaw/socket'
  localStorage.setItem('inteliscope.session-cleanup.v1:'+encodeURIComponent(user)+':'+encodeURIComponent(gateway),'off')
 },{user,a})
 await page.routeWebSocket('**/api/me/openclaw/socket',socket=>{
  socket.onMessage(raw=>{
   const frame=JSON.parse(String(raw));const {method,params={}}=frame;methods.push(method)
   let payload:unknown={ok:true}
   if(method==='connect')payload={protocol:4,auth:{role:'operator',scopes:['operator.read','operator.write']},snapshot:{sessionDefaults:{defaultAgentId:'main'}},features:{methods:['sessions.preview','sessions.list','sessions.describe','sessions.delete','sessions.create']}}
   else if(method==='sessions.preview')payload={previews:params.keys.map((key:string)=>({key,status:rows.has(key)?(key.endsWith(':empty')?'empty':'ok'):'missing'}))}
   else if(method==='sessions.list'){const sessions=[...rows.values()].filter(s=>!params.search||s.key.includes(params.search));payload={sessions,totalCount:sessions.length,hasMore:false}}
   else if(method==='sessions.describe')payload={session:{...rows.get(params.key),parentSessionKey:'agent:main:main',modelProvider:'local',model:'quick'}}
   else if(method==='models.list')payload={models:[{id:'quick',provider:'local',name:'Quick',input:['text']}]}
   else if(method==='agents.list')payload={agents:[{id:'main',model:{primary:'local/quick'}}]}
   else if(method==='chat.history')payload={messages:[]}
   else if(method==='tools.effective')payload={groups:[]}
   else if(method==='sessions.delete'){payload={ok:true,deleted:rows.delete(params.key)}}
   else if(method==='sessions.create'){rows.set(c,{key:c,agentId:'main',displayName:'',updatedAt:4,hasActiveRun:false,archived:false});payload={key:c}}
   socket.send(JSON.stringify({type:'res',id:frame.id,ok:true,payload}))
  })
  socket.send(JSON.stringify({type:'event',event:'connect.challenge',payload:{nonce:'diagnostic-nonce'}}))
 })
 await page.goto('/agent')
 await expect(page.getByRole('heading',{name:'待删除 A',exact:true})).toBeVisible()
 await page.getByRole('button',{name:'打开会话：保留会话 B',exact:true}).click()
 await expect(page.getByRole('heading',{name:'保留会话 B',exact:true})).toBeVisible()
 expect(await page.evaluate(user=>sessionStorage.getItem('infohub-managed-session:'+user),user)).toBe(b)
 const row=page.locator('[data-agent-session-row]').filter({hasText:'待删除 A'})
 await row.hover();await row.getByRole('button',{name:'删除会话：待删除 A',exact:true}).click()
 await page.getByRole('dialog',{name:'删除会话',exact:true}).getByRole('button',{name:'确认删除',exact:true}).click()
 await expect(page.getByRole('button',{name:'打开会话：待删除 A',exact:true})).toHaveCount(0)
 await expect(page.getByRole('heading',{name:'保留会话 B',exact:true})).toBeVisible()
 await expect(page.getByTestId('openclaw-composer-textarea')).toBeVisible()
 await page.screenshot({path:info.outputPath('before-refresh.png')})
 await page.reload()
 await expect(page.getByRole('heading',{name:'保留会话 B',exact:true})).toBeVisible()
 await expect(page.getByRole('button',{name:'打开会话：保留会话 B',exact:true})).toBeVisible()
 expect(methods.filter(m=>m==='sessions.create')).toHaveLength(0)
 expect(methods.filter(m=>m==='chat.send')).toHaveLength(0)
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
 expect(errors).toEqual([])
 await expect(page.getByTestId('openclaw-composer-textarea')).toBeVisible()
 await page.screenshot({path:info.outputPath('after-refresh.png')})
 await expect(page.getByText(/当前会话的模型继承异常/)).toHaveCount(0)
 expect(rows.has(a)).toBe(false)
 expect(rows.has(c)).toBe(false)
 await page.getByRole('button',{name:'新对话',exact:true}).click()
 await expect(page.getByRole('heading',{name:'新对话',exact:true})).toBeVisible()
 await expect(page.getByText(/当前会话的模型继承异常/)).toHaveCount(0)
 expect(methods.filter(m=>m==='sessions.create')).toHaveLength(1)
 const day=86_400_000
 for(const [id,age] of [['empty',8],['history-old',91],['history-recent',89]] as const){
  const key='agent:main:'+id
  rows.set(key,{key,agentId:'main',displayName:id,updatedAt:Date.now()-age*day,hasActiveRun:false,archived:false})
 }
 await page.getByRole('button',{name:'全部会话',exact:true}).click()
 const history=page.getByRole('dialog',{name:'全部会话',exact:true})
 const cleanup=history.getByRole('switch',{name:'自动清理闲置会话'})
 await expect(cleanup).not.toBeChecked()
 await history.getByText('自动清理闲置会话',{exact:true}).click()
 await expect(history.getByText('已自动清理 2 个闲置会话。')).toBeVisible({timeout:15000})
 expect(rows.has('agent:main:empty')).toBe(false)
 expect(rows.has('agent:main:history-old')).toBe(false)
 expect(rows.has('agent:main:history-recent')).toBe(true)
 expect(rows.has(c)).toBe(true)
 await page.screenshot({path:info.outputPath('session-cleanup.png')})
})
