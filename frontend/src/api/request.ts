import axios, { type AxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const instance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

instance.interceptors.request.use((config) => {
  const authStore = useAuthStore()
  if (authStore.token) {
    config.headers.Authorization = `Bearer ${authStore.token}`
  }
  return config
})

instance.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    let msg = '请求失败'
    const data = error.response?.data
    if (typeof data?.detail === 'string') {
      msg = data.detail
    } else if (data?.detail?.code === 'QUOTA_EXCEEDED') {
      msg = data.detail.reason === 'page_limit'
        ? `合同共 ${data.detail.used} 页，超出免费版 ${data.detail.limit} 页限制`
        : `本月免费审查额度已用完（${data.detail.used}/${data.detail.limit}）`
    } else if (data instanceof Blob && data.type === 'application/json') {
      try {
        const text = await data.text()
        const parsed = JSON.parse(text)
        msg = parsed.detail || '请求失败'
      } catch {
        // 解析失败时使用默认提示
      }
    }
    ElMessage.error(msg)
    // 401 统一登出跳转，但登录接口本身除外（输错密码不该触发重定向刷新）
    const isLoginRequest = (error.config?.url || '').includes('/auth/login')
    if (error.response?.status === 401 && !isLoginRequest) {
      const authStore = useAuthStore()
      authStore.logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

const request = {
  get<T = any>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return instance.get(url, config)
  },
  post<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return instance.post(url, data, config)
  },
  put<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return instance.put(url, data, config)
  },
  delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return instance.delete(url, config)
  },
}

export default request
