import { useState } from 'react'
import { toast } from 'sonner'
import LogoMark from './LogoMark.jsx'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setLoading(true)
    try {
      const res = await fetch(`${BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })
      const data = await res.json()
      if (!res.ok) {
        toast.error(data.error ?? 'Credenciales incorrectas')
        return
      }
      localStorage.setItem('rf_token', data.token)
      onLogin(data)
    } catch {
      toast.error('No se pudo conectar con el servidor')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-app-bg flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo / title */}
        <div className="mb-8 flex flex-col items-center justify-center gap-4">
          <div className="flex items-center justify-center gap-4">
            <LogoMark className="h-16 w-auto sm:h-20" alt="" />
            <h1 className="text-4xl font-bold text-accent sm:text-5xl">Signa</h1>
          </div>
        </div>

        {/* Card */}
        <form
          onSubmit={handleSubmit}
          className="bg-app-surface border border-app-border rounded-2xl p-6 shadow-xl space-y-4"
        >
          <div className="space-y-1">
            <label className="text-xs font-medium text-app-muted uppercase tracking-wider">
              Usuario
            </label>
            <input
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loading}
              placeholder="nombre de usuario"
              className="w-full bg-app-bg border border-app-border rounded-lg px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:opacity-50"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-app-muted uppercase tracking-wider">
              Contraseña
            </label>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
              placeholder="••••••••"
              className="w-full bg-app-bg border border-app-border rounded-lg px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:opacity-50"
            />
          </div>

          <button
            type="submit"
            disabled={loading || !username.trim() || !password}
            className="w-full bg-teal-600 hover:bg-teal-500 disabled:bg-teal-800 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg text-sm transition-colors"
          >
            {loading ? 'Ingresando…' : 'Ingresar'}
          </button>
        </form>
      </div>
    </div>
  )
}
