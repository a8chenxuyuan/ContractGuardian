export interface User {
  id: number
  email: string
  nickname: string | null
  is_active: boolean
  is_admin: boolean
  is_member: boolean
  membership_expire_at: string | null
  created_at: string
}

export interface MembershipPlan {
  plan_type: string
  name: string
  price: number
  duration_days: number
  description: string
  features: string[]
  recommended: boolean
}

export interface MembershipMe {
  is_member: boolean
  membership_expire_at: string | null
  page_limit: number | null
  monthly_reviews_used: number
  monthly_reviews_limit: number | null
}

export interface RedeemResult {
  order_no?: string
  amount?: number
  plan_type: string
  is_member: boolean
  membership_expire_at: string | null
  message: string
}

export interface AdminUser extends User {
  contract_count: number
  review_count: number
}

export interface AppNotification {
  id: number
  user_id: number
  title: string
  content: string | null
  type: string
  contract_id: number | null
  related_id: number | null
  is_read: boolean
  created_at: string
}

export interface AuditLog {
  id: number
  user_id: number | null
  email: string | null
  action: string
  resource: string
  ip: string | null
  created_at: string
}

export interface KnowledgeArticle {
  id: number
  law_name: string
  article_number: string
  article_title: string | null
  article_text: string
  category: string
}

export interface KnowledgeCase {
  id: number
  title: string
  summary: string | null
  court: string | null
  verdict: string | null
  related_articles: string[]
  source_url: string | null
}

export interface AdminStats {
  user_total: number
  active_users: number
  contract_total: number
  review_total: number
  completed_reviews: number
  risk_levels: { high: number; medium: number; low: number }
  review_trend: { date: string; count: number }[]
  top_risk_types: { type: string; count: number }[]
}

export interface MyStats {
  contract_count: number
  review_count: number
  risk_levels: { high: number; medium: number; low: number }
  recent_reviews: { id: number; status: string; created_at: string; contract_id: number; filename: string }[]
}

export interface Contract {
  id: number
  filename: string
  file_type: string
  status: string
  page_count: number | null
  risk_summary: Record<string, number> | null
  file_url: string | null
  latest_review_session_id: number | null
  version_count: number
  nearest_expiry: string | null
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type FindingStatus = 'active' | 'confirmed' | 'dismissed' | 'resolved'

export interface Finding {
  id?: number
  clause_text: string
  risk_type: string
  level: 'high' | 'medium' | 'low'
  confidence: number
  reason: string
  law_refs: string[]
  suggestion: {
    original_text: string
    revised_text: string
    rationale: string
  }
  page?: number
  bbox?: {
    x: number
    y: number
    w: number
    h: number
  } | null
  status?: FindingStatus
  resolution_note?: string | null
  resolved_at?: string | null
}

export interface ReviewResult {
  id: number
  contract_id: number
  status: string
  fail_reason?: string | null
  findings: Finding[]
  graph_data: any
  stats: Record<string, number> | null
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}
