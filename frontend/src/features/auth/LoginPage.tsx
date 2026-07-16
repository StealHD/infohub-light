import { useState, type FormEvent } from 'react'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import styles from './LoginPage.module.css'

type LoginPageProps = {
  api: ServiceApi
  onAuthenticated: () => void
}

export function LoginPage({ api, onAuthenticated }: LoginPageProps) {
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

  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="login-title">
        <div className={styles.brand}>Inteliscope</div>
        <h1 id="login-title">登录私人信息雷达</h1>
        <p>订阅、获取并留存真正需要的信息。</p>
        <form onSubmit={submit}>
          <label>用户名<input name="username" autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} /></label>
          <label>密码<input name="password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          {error && <div className={styles.error} role="alert">{error}</div>}
          <button type="submit" disabled={pending}>{pending ? '登录中…' : '登录'}</button>
        </form>
      </section>
    </main>
  )
}
