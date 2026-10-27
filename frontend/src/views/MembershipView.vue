<template>
  <div class="membership-page">
    <!-- 当前状态卡 -->
    <div class="status-card" :class="{ member: me?.is_member }">
      <div class="status-left">
        <div class="status-badge">
          <el-icon :size="22"><service /></el-icon>
          <span>{{ me?.is_member ? '会员用户' : '免费版' }}</span>
        </div>
        <h3 class="status-title">
          {{ me?.is_member ? `会员有效期至 ${formatDate(me.membership_expire_at)}` : '升级会员，解锁无限审查' }}
        </h3>
        <p class="status-sub">
          {{
            me?.is_member
              ? '会员期间单合同页数与每月审查次数均无限制'
              : `免费版：单合同 ≤ ${me?.page_limit ?? 20} 页 · 每月 ${me?.monthly_reviews_limit ?? 3} 次审查`
          }}
        </p>
      </div>
      <div class="status-usage" v-if="!me?.is_member">
        <div class="usage-ring">
          <el-progress
            type="dashboard"
            :percentage="usagePercent"
            :width="96"
            :stroke-width="9"
            :color="progressColor"
          >
            <template #default>
              <span class="usage-num">{{ me?.monthly_reviews_used ?? 0 }}/{{ me?.monthly_reviews_limit ?? 3 }}</span>
              <span class="usage-label">本月已审查</span>
            </template>
          </el-progress>
        </div>
      </div>
    </div>

    <!-- 套餐区 -->
    <div class="plans-grid" v-loading="loading">
      <div
        v-for="plan in plans"
        :key="plan.plan_type"
        class="plan-card cg-card"
        :class="{ recommended: plan.recommended }"
      >
        <div class="plan-flag" v-if="plan.recommended">最受欢迎</div>
        <h4 class="plan-name">{{ plan.name }}</h4>
        <div class="plan-price">
          <span class="price-num">¥{{ plan.price }}</span>
          <span class="price-unit">/ {{ plan.duration_days >= 365 ? '年' : '月' }}</span>
        </div>
        <p class="plan-desc">{{ plan.description }}</p>
        <ul class="plan-features">
          <li v-for="f in plan.features" :key="f">
            <el-icon><circle-check /></el-icon>{{ f }}
          </li>
        </ul>
        <el-button
          type="primary"
          round
          class="plan-btn"
          :loading="ordering === plan.plan_type"
          @click="handleOrder(plan)"
        >
          {{ me?.is_member ? '续费开通' : '立即开通' }}
        </el-button>
      </div>
    </div>

    <!-- 兑换码 -->
    <div class="redeem-card cg-card">
      <h4><el-icon><ticket /></el-icon> 使用兑换码开通</h4>
      <div class="redeem-row">
        <el-input
          v-model="redeemCode"
          placeholder="输入兑换码，如 CG-M-XXXXXXXXXXXX"
          size="large"
          clearable
          @keyup.enter="handleRedeem"
        />
        <el-button type="primary" size="large" round :loading="redeeming" @click="handleRedeem">
          立即兑换
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Service, CircleCheck, Ticket } from '@element-plus/icons-vue'
import {
  getMembershipPlans,
  getMyMembership,
  createMembershipOrder,
  redeemMembershipCode,
} from '@/api/membership'
import type { MembershipPlan, MembershipMe } from '@/types'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const plans = ref<MembershipPlan[]>([])
const me = ref<MembershipMe | null>(null)
const ordering = ref<string | null>(null)
const redeemCode = ref('')
const redeeming = ref(false)

const usagePercent = computed(() => {
  if (!me.value || !me.value.monthly_reviews_limit) return 0
  return Math.min(100, Math.round((me.value.monthly_reviews_used / me.value.monthly_reviews_limit) * 100))
})

const progressColor = computed(() => {
  if (usagePercent.value >= 100) return '#ef4444'
  if (usagePercent.value >= 66) return '#f59e0b'
  return '#6366f1'
})

function formatDate(iso: string | null) {
  if (!iso) return '-'
  return new Date(iso).toLocaleDateString('zh-CN')
}

async function loadData() {
  loading.value = true
  try {
    const [plansRes, meRes] = await Promise.all([getMembershipPlans(), getMyMembership()])
    plans.value = plansRes.plans
    me.value = meRes
  } finally {
    loading.value = false
  }
}

async function handleOrder(plan: MembershipPlan) {
  ordering.value = plan.plan_type
  try {
    const res = await createMembershipOrder(plan.plan_type as 'monthly' | 'yearly')
    ElMessage.success(res.message)
    await loadData()
    await authStore.fetchMe()
  } finally {
    ordering.value = null
  }
}

async function handleRedeem() {
  if (!redeemCode.value.trim()) {
    ElMessage.warning('请输入兑换码')
    return
  }
  redeeming.value = true
  try {
    const res = await redeemMembershipCode(redeemCode.value.trim())
    ElMessage.success(res.message)
    redeemCode.value = ''
    await loadData()
    await authStore.fetchMe()
  } finally {
    redeeming.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.membership-page {
  max-width: 1080px;
  margin: 0 auto;
}

/* ---------- 状态卡 ---------- */
.status-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  border-radius: var(--cg-radius);
  padding: 28px 32px;
  margin-bottom: 22px;
  background: linear-gradient(135deg, #eef2ff 0%, #faf5ff 100%);
  border: 1px solid #e0e7ff;
}

.status-card.member {
  background: var(--cg-gradient);
  border: none;
  color: #fff;
  box-shadow: 0 12px 32px rgba(79, 70, 229, 0.3);
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.85);
  color: var(--cg-primary);
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 12px;
}

.status-card.member .status-badge {
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
}

.status-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--cg-text);
  margin: 0 0 6px;
}

.status-card.member .status-title {
  color: #fff;
}

.status-sub {
  font-size: 13px;
  color: var(--cg-text-muted);
  margin: 0;
}

.status-card.member .status-sub {
  color: rgba(255, 255, 255, 0.85);
}

.usage-num {
  font-size: 18px;
  font-weight: 700;
  color: var(--cg-text);
  display: block;
}

.usage-label {
  font-size: 11px;
  color: var(--cg-text-muted);
}

/* ---------- 套餐 ---------- */
.plans-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-bottom: 22px;
}

.plan-card {
  position: relative;
  padding: 28px;
  display: flex;
  flex-direction: column;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.plan-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 14px 36px rgba(79, 70, 229, 0.14);
}

.plan-card.recommended {
  border: 1.5px solid var(--cg-primary);
}

.plan-flag {
  position: absolute;
  top: -1px;
  right: 24px;
  background: var(--cg-gradient);
  color: #fff;
  font-size: 11.5px;
  padding: 4px 12px;
  border-radius: 0 0 8px 8px;
}

.plan-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--cg-text);
  margin: 0 0 10px;
}

.plan-price {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 8px;
}

.price-num {
  font-size: 32px;
  font-weight: 800;
  background: var(--cg-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.price-unit {
  font-size: 13px;
  color: var(--cg-text-muted);
}

.plan-desc {
  font-size: 12.5px;
  color: var(--cg-text-muted);
  margin: 0 0 14px;
}

.plan-features {
  list-style: none;
  padding: 0;
  margin: 0 0 20px;
  display: flex;
  flex-direction: column;
  gap: 9px;
  flex: 1;
}

.plan-features li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--cg-text-secondary);
}

.plan-features .el-icon {
  color: #10b981;
  flex-shrink: 0;
}

.plan-btn {
  width: 100%;
}

/* ---------- 兑换码 ---------- */
.redeem-card {
  padding: 22px 28px;
}

.redeem-card h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14.5px;
  color: var(--cg-text);
  margin: 0 0 14px;
}

.redeem-card h4 .el-icon {
  color: var(--cg-primary);
}

.redeem-row {
  display: flex;
  gap: 12px;
}

.redeem-row .el-input {
  max-width: 420px;
}

@media (max-width: 760px) {
  .plans-grid {
    grid-template-columns: 1fr;
  }

  .status-card {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
