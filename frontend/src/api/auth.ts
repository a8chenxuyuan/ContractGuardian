import request from './request'
import type { MyStats, User } from '@/types'

export interface LoginForm {
  email: string
  password: string
}

export interface RegisterForm {
  email: string
  password: string
  nickname?: string
}

export function login(data: LoginForm) {
  const params = new URLSearchParams()
  params.append('username', data.email)
  params.append('password', data.password)
  return request.post<{ access_token: string }>('/auth/login', params, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
}

export function register(data: RegisterForm) {
  return request.post<User>('/auth/register', data)
}

export function getMe() {
  return request.get<User>('/auth/me')
}

export function updateProfile(data: { nickname?: string }) {
  return request.put<User>('/auth/me', data)
}

export function changePassword(data: { old_password: string; new_password: string }) {
  return request.put<{ message: string }>('/auth/password', data)
}

export function forgotPassword(email: string) {
  return request.post<{ message: string }>('/auth/forgot-password', { email })
}

export function resetPassword(data: { email: string; code: string; new_password: string }) {
  return request.post<{ message: string }>('/auth/reset-password', data)
}

export function getMyStats() {
  return request.get<MyStats>('/auth/me/stats')
}
