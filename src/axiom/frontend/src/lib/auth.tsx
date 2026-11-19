import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { api, setToken, token } from "@/lib/api"
import type { User } from "@/lib/types"

type AuthValue = {
  user: User | null
  ready: boolean
  login: (username: string, password: string) => Promise<User>
  logout: () => Promise<void>
  refresh: (user: User) => void
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!token()) {
      setReady(true)
      return
    }
    api.me().then(setUser).catch(() => setToken(null)).finally(() => setReady(true))
  }, [])

  const value = useMemo<AuthValue>(
    () => ({
      user,
      ready,
      async login(username, password) {
        const result = await api.login(username, password)
        setToken(result.token)
        setUser(result.user)
        return result.user
      },
      async logout() {
        try {
          await api.logout()
        } catch {
          /* the local session still ends */
        }
        setToken(null)
        setUser(null)
      },
      refresh(next) {
        setUser(next)
      },
    }),
    [ready, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error("AuthProvider missing")
  return value
}
