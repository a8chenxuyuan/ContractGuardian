import request from './request'

export interface DashboardSummary {
  risk_levels: { high: number; medium: number; low: number }
  rectification: {
    total: number
    resolved: number
    dismissed: number
    closed: number
    close_rate: number
  }
  top_risk_types: { type: string; count: number }[]
  reviews_30d: number
  review_trend: { date: string; count: number }[]
  contract_count: number
  upcoming_dates: UpcomingDate[]
}

export interface UpcomingDate {
  id: number
  contract_id: number
  review_session_id: number
  filename: string
  date_value: string
  date_type: string
  raw_text: string
  days_left: number
}

export interface CalendarItem {
  id: number
  contract_id: number
  review_session_id: number
  filename: string
  date_value: string
  date_type: string
  raw_text: string
  context: string | null
  days_left: number
}

export interface CalendarMonth {
  year: number
  month: number
  today: string
  items: CalendarItem[]
}

export function getDashboardSummary() {
  return request.get<DashboardSummary>('/dashboard/summary')
}

export function getCalendar(year?: number, month?: number) {
  return request.get<CalendarMonth>('/calendar', { params: { year, month } })
}
