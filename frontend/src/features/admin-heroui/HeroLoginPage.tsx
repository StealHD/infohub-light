import { useRef, useState, type FormEvent } from 'react'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import {
  Button,
  Card,
  FieldError,
  Form,
  Icons,
  Input,
  InputGroup,
  Label,
  PageFrame,
  ThemeModeToggle,
  TextField,
} from '../../design-system'
import { HeroNotice } from './HeroAdminControls'

export function HeroLoginPage({ api, onAuthenticated }: { api: ServiceApi; onAuthenticated: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const pendingRef = useRef(false)

  function updateUsername(value: string) {
    setUsername(value)
    if (error) setError('')
  }

  function updatePassword(value: string) {
    setPassword(value)
    if (error) setError('')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pendingRef.current) return
    pendingRef.current = true
    setError('')
    setPasswordVisible(false)
    setPending(true)
    try {
      const result = await api.login(username.trim(), password)
      setPassword('')
      if (!result.authenticated || !result.user) throw new Error('登录会话未建立')
      onAuthenticated()
    } catch (caught) {
      setPassword('')
      setError(caught instanceof ApiError ? caught.message : '登录失败，请检查账号和密码。')
    } finally {
      pendingRef.current = false
      setPending(false)
    }
  }

  return <main className="relative grid min-h-dvh place-items-center overflow-x-hidden bg-background px-4 pb-4 pt-16 min-[768px]:p-6">
    <div className="absolute right-3 top-3 z-10"><ThemeModeToggle /></div>
    <PageFrame width="auth">
      <Card
        variant="secondary"
        data-login-layout="quiet-studio-split"
        className="grid w-full overflow-hidden border border-separator bg-surface p-0 shadow-none min-[768px]:grid-cols-[11fr_12fr]"
        aria-labelledby="hero-login-title"
      >
        <section
          data-login-brand
          aria-label="Inteliscope 产品简介"
          className="flex flex-col border-b border-separator bg-surface-secondary p-6 min-[768px]:min-h-[520px] min-[768px]:justify-between min-[768px]:border-b-0 min-[768px]:border-r min-[768px]:p-10"
        >
          <div>
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-accent text-accent-foreground"><Icons.InteliscopeMark size={21} aria-hidden="true" /></span>
              <span className="type-page-title">Inteliscope</span>
            </div>
            <p className="type-section-title mt-8 max-w-xs">专注你真正关心的信息</p>
            <p className="type-body mt-3 max-w-sm text-muted">订阅、获取并留存真正需要的信息。</p>
          </div>
          <ul className="mt-8 hidden gap-4 min-[768px]:grid" aria-label="产品能力">
            <li className="flex items-start gap-3">
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-control border border-separator bg-surface text-accent"><Icons.Rss size={16} aria-hidden="true" /></span>
              <span><span className="type-control block">多源订阅</span><span className="type-meta mt-0.5 block text-muted">把关注的来源收进一个工作台</span></span>
            </li>
            <li className="flex items-start gap-3">
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-control border border-separator bg-surface text-accent"><Icons.Rows3 size={16} aria-hidden="true" /></span>
              <span><span className="type-control block">统一信息流</span><span className="type-meta mt-0.5 block text-muted">按自己的节奏集中阅读</span></span>
            </li>
            <li className="flex items-start gap-3">
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-control border border-separator bg-surface text-accent"><Icons.History size={16} aria-hidden="true" /></span>
              <span><span className="type-control block">稳定留存</span><span className="type-meta mt-0.5 block text-muted">收藏与历史始终属于当前账户</span></span>
            </li>
          </ul>
        </section>
        <section data-login-form className="flex items-center bg-surface p-6 min-[640px]:p-8 min-[768px]:p-10">
          <div className="w-full">
            <h1 id="hero-login-title" className="type-display">登录私人信息雷达</h1>
            <Card.Description className="mt-2">使用你的工作区账号继续。</Card.Description>
            <Form
              aria-label="登录"
              aria-busy={pending || undefined}
              aria-describedby={error ? 'hero-login-error' : undefined}
              onSubmit={submit}
              className="mt-7 grid gap-4"
            >
              <TextField autoFocus fullWidth isRequired isDisabled={pending} value={username} onChange={updateUsername} name="username">
                <Label>用户名</Label>
                <Input autoComplete="username" />
                <FieldError />
              </TextField>
              <TextField fullWidth isRequired isDisabled={pending} value={password} onChange={updatePassword} name="password">
                <Label>密码</Label>
                <InputGroup fullWidth variant="primary">
                  <InputGroup.Input type={passwordVisible ? 'text' : 'password'} autoComplete="current-password" />
                  <InputGroup.Suffix>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      isIconOnly
                      isDisabled={pending}
                      aria-label={passwordVisible ? '隐藏密码' : '显示密码'}
                      aria-pressed={passwordVisible}
                      className="text-muted hover:text-foreground"
                      onClick={(event) => event.stopPropagation()}
                      onPress={() => setPasswordVisible((visible) => !visible)}
                    >
                      {passwordVisible ? <Icons.EyeOff size={16} aria-hidden="true" /> : <Icons.Eye size={16} aria-hidden="true" />}
                    </Button>
                  </InputGroup.Suffix>
                </InputGroup>
                <FieldError />
              </TextField>
              {error && <div id="hero-login-error"><HeroNotice title={error} /></div>}
              <Button type="submit" fullWidth isPending={pending} isDisabled={pending}>{pending ? '登录中…' : '登录'}</Button>
            </Form>
          </div>
        </section>
      </Card>
    </PageFrame>
  </main>
}
