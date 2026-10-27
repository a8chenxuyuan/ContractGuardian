import request from './request'
import type { MembershipPlan, MembershipMe, RedeemResult } from '@/types'

export function getMembershipPlans() {
  return request.get<{ plans: MembershipPlan[]; free_limits: Record<string, number> }>('/membership/plans')
}

export function getMyMembership() {
  return request.get<MembershipMe>('/membership/me')
}

export function createMembershipOrder(planType: 'monthly' | 'yearly') {
  return request.post<RedeemResult>('/membership/order', { plan_type: planType })
}

export function redeemMembershipCode(code: string) {
  return request.post<RedeemResult>('/membership/redeem', { code })
}
