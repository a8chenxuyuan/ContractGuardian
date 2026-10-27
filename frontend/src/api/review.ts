import axios from 'axios'
import request from './request'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import type { ReviewResult, Finding } from '@/types'

export function startReview(contractId: number, baseVersion?: number) {
  return request.post<{ review_session_id: number; message: string }>(
    `/review/${contractId}/review`,
    baseVersion ? { base_version: baseVersion } : {}
  )
}

export interface DiffSummary {
  summary: {
    total_base: number
    total_target: number
    added: number
    removed: number
    modified: number
    unchanged: number
  } | null
  changes: {
    type: 'added' | 'removed' | 'modified'
    base: { title: string; text: string } | null
    target: { title: string; text: string } | null
    ratio: number | null
  }[]
  error?: string
}

export function getReviewDiff(sessionId: number) {
  return request.get<{ base_version: number | null; status: string; diff: DiffSummary | null }>(
    `/review/${sessionId}/diff`
  )
}

export function getReviewStreamUrl(sessionId: number) {
  // SSE 用 EventSource 建连，无法携带 Authorization Header，token 走 query 参数
  const authStore = useAuthStore()
  const token = authStore.token || ''
  return `/api/v1/review/${sessionId}/stream?token=${encodeURIComponent(token)}`
}

export function getReviewResult(sessionId: number) {
  return request.get<ReviewResult>(`/review/${sessionId}/result`)
}

export function cancelReview(sessionId: number) {
  return request.post<{ id: number; status: string; fail_reason: string }>(
    `/review/${sessionId}/cancel`
  )
}

export function getFindings(sessionId: number) {
  return request.get<Finding[]>(`/review/${sessionId}/findings`)
}

export function updateFindingStatus(findingId: number, status: string, note?: string) {
  return request.put<{ id: number; status: string; resolution_note: string | null; resolved_at: string | null }>(
    `/review/findings/${findingId}/status`,
    { status, note: note || null }
  )
}

export interface Rectification {
  total: number
  active: number
  confirmed: number
  dismissed: number
  resolved: number
  close_rate: number
}

export function getRectification(sessionId: number) {
  return request.get<Rectification>(`/review/${sessionId}/rectification`)
}

export interface ShareInfo {
  token: string
  url: string
  expires_at: string
}

export function createShareLink(sessionId: number) {
  return request.post<ShareInfo>(`/review/${sessionId}/share`)
}

export interface SharedReport {
  contract_filename: string
  status: string
  completed_at: string | null
  base_version: number | null
  findings: Finding[]
  stats: Record<string, number> | null
  diff: DiffSummary | null
  expires_at: string
}

export function getSharedReport(token: string) {
  return request.get<SharedReport>(`/review/share/${token}`)
}

export async function exportReport(sessionId: number, format: 'pdf' | 'word') {
  return downloadBlob('post', `/api/v1/review/${sessionId}/export?format=${format}`)
}

export function exportMarkedReport(sessionId: number) {
  return downloadBlob('get', `/api/v1/review/${sessionId}/export/marked`)
}

async function downloadBlob(method: 'get' | 'post', url: string): Promise<Blob> {
  const authStore = useAuthStore()
  try {
    const res = await axios.request({
      method,
      url,
      responseType: 'blob',
      headers: authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {},
    })
    return res.data
  } catch (error: any) {
    let msg = '导出失败'
    const data = error.response?.data
    if (data instanceof Blob) {
      try {
        const text = await data.text()
        const parsed = JSON.parse(text)
        msg = parsed.detail || msg
      } catch {
        // 忽略解析失败
      }
    } else if (error.response?.data?.detail) {
      msg = error.response.data.detail
    } else if (error.message) {
      msg = error.message
    }
    ElMessage.error(msg)
    throw error
  }
}

// ---------- 划词追问 ----------
export interface AskResult {
  answer: string
  references: Record<string, any>[]
  degraded: boolean
}

export function askAboutFinding(
  sessionId: number,
  question: string,
  selectedText?: string,
  findingId?: number
) {
  // 检索（BGE-M3 编码+重排）+ LLM 生成耗时超过全局 30s，单独放宽
  return request.post<AskResult>(
    `/review/${sessionId}/ask`,
    {
      question,
      selected_text: selectedText || null,
      finding_id: findingId ?? null,
    },
    { timeout: 120000 }
  )
}
