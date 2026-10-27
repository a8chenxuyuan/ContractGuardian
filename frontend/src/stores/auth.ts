import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMe } from '@/api/auth'
import type { User } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const user = ref<User | null>(null)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => !!user.value?.is_admin)

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  function setUser(newUser: User) {
    user.value = newUser
  }

  /** 刷新页面后用户信息丢失，用 token 兜底拉取。 */
  async function fetchMe() {
    if (!token.value) return
    try {
      user.value = await getMe()
    } catch {
      // 401 时由请求拦截器统一登出
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
  }

  return {
    token,
    user,
    isLoggedIn,
    isAdmin,
    setToken,
    setUser,
    fetchMe,
    logout,
  }
})
