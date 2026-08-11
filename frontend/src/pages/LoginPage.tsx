import { useState } from 'react'
import { api, ApiError } from '../api'

export function LoginPage() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const signInWithGoogle = async () => {
    setBusy(true)
    setError('')
    try {
      const { url } = await api.loginUrl()
      window.location.href = url
    } catch (err) {
      setBusy(false)
      setError(
        err instanceof ApiError
          ? err.message
          : 'Google sign-in is not configured on this server.',
      )
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <h1>Voice Studio</h1>
        <p className="login-subtitle">
          Design a custom voice and generate narrated audio from any script.
        </p>
        <button
          className="btn btn-primary btn-block"
          onClick={signInWithGoogle}
          disabled={busy}
        >
          {busy ? 'Redirecting…' : 'Continue with Google'}
        </button>
        {error && <p className="error-banner">{error}</p>}
        <p className="login-hint">
          Demo mode: ask the server operator to enable the development login
          (DEV_LOGIN=1) for a test sign-in.
        </p>
      </div>
    </div>
  )
}
