import { useState, type FormEvent } from 'react'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import {
  Button,
  Card,
  DesignSystemProvider,
  FieldError,
  Form,
  Icons,
  Input,
  Label,
  TextField,
} from '../../design-system'
import { HeroNotice } from './HeroAdminControls'

export function HeroLoginPage({ api, onAuthenticated }: { api: ServiceApi; onAuthenticated: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
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
      setPending(false)
    }
  }

  return <DesignSystemProvider>
    <main className="grid min-h-dvh place-items-center bg-background p-4">
      <Card variant="secondary" className="w-full max-w-md p-6 min-[640px]:p-8" aria-labelledby="hero-login-title">
        <div className="mb-6 flex size-10 items-center justify-center rounded-xl bg-accent text-accent-foreground"><Icons.Radar size={21} aria-hidden="true" /></div>
        <Card.Title id="hero-login-title" className="text-2xl">登录私人信息雷达</Card.Title>
        <Card.Description className="mt-2">订阅、获取并留存真正需要的信息。</Card.Description>
        <Form onSubmit={submit} className="mt-6 grid gap-4">
          <TextField fullWidth isRequired value={username} onChange={setUsername} name="username">
            <Label>用户名</Label>
            <Input autoComplete="username" />
            <FieldError />
          </TextField>
          <TextField fullWidth isRequired value={password} onChange={setPassword} name="password">
            <Label>密码</Label>
            <Input type="password" autoComplete="current-password" />
            <FieldError />
          </TextField>
          {error && <HeroNotice title={error} />}
          <Button type="submit" fullWidth isPending={pending} isDisabled={pending}>{pending ? '登录中…' : '登录'}</Button>
        </Form>
      </Card>
    </main>
  </DesignSystemProvider>
}
