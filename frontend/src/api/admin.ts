import request from './request'
import type { AdminUser, AdminStats, AppNotification, AuditLog, KnowledgeArticle, KnowledgeCase } from '@/types'

// ---------- 用户管理 ----------

export function listUsers(params: { skip?: number; limit?: number; keyword?: string }) {
  return request.get<{ total: number; items: AdminUser[] }>('/admin/users', { params })
}

export function setUserStatus(userId: number, isActive: boolean) {
  return request.put<{ message: string }>(`/admin/users/${userId}/status`, { is_active: isActive })
}

export function setUserRole(userId: number, data: { is_admin: boolean; is_member: boolean }) {
  return request.put<{ message: string }>(`/admin/users/${userId}/role`, data)
}

export function resetUserPassword(userId: number, newPassword: string) {
  return request.put<{ message: string }>(`/admin/users/${userId}/password`, { new_password: newPassword })
}

export function deleteUser(userId: number) {
  return request.delete<{ message: string }>(`/admin/users/${userId}`)
}

// ---------- 审查记录 ----------

export function listAllReviews(params: { skip?: number; limit?: number }) {
  return request.get<{
    total: number
    items: {
      id: number
      contract_id: number
      filename: string
      owner: string
      status: string
      created_at: string
      completed_at: string | null
    }[]
  }>('/admin/reviews', { params })
}

// ---------- 人工复核 ----------

export interface HumanReviewItem {
  id: number
  review_session_id: number
  finding_id: number | null
  reason: string
  status: string
  reviewer_id: number | null
  comment: string | null
  created_at: string
  resolved_at: string | null
}

export function listHumanReviews(params?: { status?: string }) {
  return request.get<HumanReviewItem[]>('/admin/human-reviews', { params })
}

export function resolveHumanReview(reviewId: number, action: 'approve' | 'reject', comment?: string) {
  return request.post<{ message: string }>(`/admin/human-reviews/${reviewId}/resolve`, null, {
    params: { action, comment },
  })
}

// ---------- 知识库 ----------

export function listArticles(params: {
  skip?: number
  limit?: number
  keyword?: string
  category?: string
}) {
  return request.get<{ total: number; items: KnowledgeArticle[] }>('/admin/knowledge/articles', { params })
}

export function createArticle(data: Partial<KnowledgeArticle>) {
  return request.post<{ record: KnowledgeArticle; vectorized: number }>('/admin/knowledge/articles', data)
}

export function updateArticle(id: number, data: Partial<KnowledgeArticle>) {
  return request.put<{ record: KnowledgeArticle; vectorized: number }>(
    `/admin/knowledge/articles/${id}`,
    data,
  )
}

export function deleteArticle(id: number) {
  return request.delete<{ message: string; vector_deleted: boolean }>(`/admin/knowledge/articles/${id}`)
}

export function importKnowledgeArticles(articles: Record<string, unknown>[]) {
  return request.post<{
    imported: number
    updated: number
    skipped: number
    vectorized: number
  }>('/admin/knowledge/articles/import', { articles }, { timeout: 300000 })
}

export function listCases(params: { skip?: number; limit?: number; keyword?: string }) {
  return request.get<{ total: number; items: KnowledgeCase[] }>('/admin/knowledge/cases', { params })
}

export function createCase(data: Partial<KnowledgeCase>) {
  return request.post<KnowledgeCase>('/admin/knowledge/cases', data)
}

export function updateCase(id: number, data: Partial<KnowledgeCase>) {
  return request.put<KnowledgeCase>(`/admin/knowledge/cases/${id}`, data)
}

export function deleteCase(id: number) {
  return request.delete<{ message: string }>(`/admin/knowledge/cases/${id}`)
}

// ---------- 审计日志与统计 ----------

export function listAuditLogs(params: {
  skip?: number
  limit?: number
  action?: string
  keyword?: string
}) {
  return request.get<{ total: number; items: AuditLog[] }>('/admin/audit-logs', { params })
}

export function getAdminStats() {
  return request.get<AdminStats>('/admin/stats')
}

// ---------- 工具审批（HITL） ----------

export interface ApprovalItem {
  approval_id: string
  status: string
  tool: string
  agent_name: string
  input_preview: string
  created_at: number
}

export function listApprovals() {
  return request.get<ApprovalItem[]>('/approvals')
}

export function approveToolCall(approvalId: string) {
  return request.post<ApprovalItem>(`/approvals/${approvalId}/approve`)
}

export function denyToolCall(approvalId: string) {
  return request.post<ApprovalItem>(`/approvals/${approvalId}/deny`)
}

// ---------- 通知 ----------

export function listNotifications(params?: { skip?: number; limit?: number; is_read?: boolean }) {
  return request.get<{ total: number; unread_count: number; items: AppNotification[] }>(
    '/notifications',
    { params },
  )
}

export function getUnreadCount() {
  return request.get<{ unread_count: number }>('/notifications/unread-count')
}

export function readNotification(id: number) {
  return request.put<{ message: string }>(`/notifications/${id}/read`)
}

export function readAllNotifications() {
  return request.put<{ message: string }>('/notifications/read-all')
}
