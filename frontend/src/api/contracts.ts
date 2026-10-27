import axios from 'axios'
import request from './request'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import type { Contract } from '@/types'

export interface ContractListQuery {
  keyword?: string
  contract_status?: string
  risk?: string
  sort?: string
}

export function getContracts(query?: ContractListQuery) {
  return request.get<Contract[]>('/contracts', { params: query })
}

export function uploadContract(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post<{ id: number; filename: string; status: string; message: string }>(
    '/contracts',
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
    }
  )
}

export function getContract(id: number) {
  return request.get<Contract>(`/contracts/${id}`)
}

export interface KeyDate {
  id: number
  contract_id: number
  review_session_id: number
  date_value: string
  date_type: string
  raw_text: string
  context: string | null
}

/** 获取合同关键履约日期（履约日期管家，审查完成时自动提取） */
export function getKeyDates(contractId: number) {
  return request.get<KeyDate[]>(`/contracts/${contractId}/key-dates`)
}

export function deleteContract(id: number) {
  return request.delete<{ message: string }>(`/contracts/${id}`)
}

export function getTrashContracts() {
  return request.get<Contract[]>('/contracts/trash')
}

export function restoreContract(id: number) {
  return request.post<{ message: string }>(`/contracts/${id}/restore`)
}

export function purgeContract(id: number) {
  return request.delete<{ message: string }>(`/contracts/${id}/purge`)
}

export function reuploadContract(id: number, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post<{ id: number; filename: string; status: string; message: string }>(
    `/contracts/${id}/reupload`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  )
}

export interface ContractFileVersion {
  id: number
  version: number
  file_size: number
  is_current: boolean
  created_at: string
}

export function getContractVersions(id: number) {
  return request.get<ContractFileVersion[]>(`/contracts/${id}/versions`)
}

/** 下载指定版本的合同文件（不传版本号取最新版） */
export async function downloadContractFile(contractId: number, version?: number) {
  const authStore = useAuthStore()
  const res = await axios.get(`/api/v1/contracts/${contractId}/file`, {
    responseType: 'blob',
    params: version ? { version } : undefined,
    headers: authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {},
  })
  return res.data as Blob
}

/** 获取在线预览 URL（PDF/图片，需带 token 参数的场景请用 previewContractFile） */
export function previewUrl(contractId: number) {
  return `/api/v1/contracts/${contractId}/preview`
}

/** 拉取在线预览内容（受鉴权，返回 Blob 供 iframe/img 展示） */
export async function previewContractFile(contractId: number) {
  const authStore = useAuthStore()
  const res = await axios.get(`/api/v1/contracts/${contractId}/preview`, {
    responseType: 'blob',
    headers: authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {},
  })
  return res.data as Blob
}
