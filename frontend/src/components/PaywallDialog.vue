<template>
  <el-dialog
    :model-value="modelValue"
    width="420px"
    align-center
    :show-close="true"
    class="paywall-dialog"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="paywall-body">
      <div class="paywall-icon">
        <el-icon :size="30"><magic-stick /></el-icon>
      </div>
      <h3 class="paywall-title">{{ title }}</h3>
      <p class="paywall-desc">{{ description }}</p>
      <div class="paywall-benefits">
        <div class="benefit-item" v-for="b in benefits" :key="b">
          <el-icon><circle-check /></el-icon>{{ b }}
        </div>
      </div>
      <div class="paywall-actions">
        <el-button round @click="$emit('update:modelValue', false)">暂不需要</el-button>
        <el-button type="primary" round @click="goMembership">
          <el-icon style="margin-right: 4px"><vip-icon /></el-icon>升级会员
        </el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { MagicStick, CircleCheck, Service as VipIcon } from '@element-plus/icons-vue'

const props = defineProps<{
  modelValue: boolean
  reason?: 'monthly_reviews' | 'page_limit'
  used?: number
  limit?: number
}>()

defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const router = useRouter()

const title = computed(() =>
  props.reason === 'page_limit' ? '合同页数超出免费版限制' : '本月免费审查额度已用完',
)

const description = computed(() =>
  props.reason === 'page_limit'
    ? `该合同共 ${props.used ?? '-'} 页，免费版单合同上限 ${props.limit ?? 20} 页。升级会员后页数无限制。`
    : `免费版每月可审查 ${props.limit ?? 3} 份合同，本月已用 ${props.used ?? '-'} 次。升级会员后次数无限制。`,
)

const benefits = [
  '单合同页数 / 每月审查次数均无限制',
  '14 Agent 全维度交叉审查',
  '报告导出与风险溯源完整保留',
]

function goMembership() {
  router.push('/membership')
}
</script>

<style scoped>
.paywall-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 6px 8px 2px;
}

.paywall-icon {
  width: 64px;
  height: 64px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--cg-gradient);
  color: #fff;
  box-shadow: 0 8px 24px rgba(79, 70, 229, 0.35);
  margin-bottom: 14px;
}

.paywall-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--cg-text);
  margin: 0 0 8px;
}

.paywall-desc {
  font-size: 13px;
  color: var(--cg-text-secondary);
  line-height: 1.7;
  margin: 0 0 16px;
}

.paywall-benefits {
  width: 100%;
  background: var(--cg-gradient-soft);
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 18px;
}

.benefit-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--cg-text-secondary);
}

.benefit-item .el-icon {
  color: var(--cg-primary);
  flex-shrink: 0;
}

.paywall-actions {
  display: flex;
  gap: 12px;
  width: 100%;
}

.paywall-actions .el-button {
  flex: 1;
}
</style>
