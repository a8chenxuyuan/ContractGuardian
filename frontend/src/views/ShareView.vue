<template>
  <div class="share-page">
    <header class="share-header">
      <div class="brand">
        <span class="brand-icon"><el-icon :size="16"><lock /></el-icon></span>
        <span class="brand-name">合同卫士</span>
      </div>
      <span class="readonly-tag">只读分享报告</span>
    </header>

    <!-- 链接失效 -->
    <div class="expired-box" v-if="expired">
      <el-icon :size="44" color="#94a3b8"><circle-close-filled /></el-icon>
      <h3>分享链接已失效</h3>
      <p>链接可能已过期或被撤销，请联系分享者重新获取。</p>
    </div>

    <!-- 报告主体 -->
    <main class="share-body" v-else>
      <div class="share-title">
        <h2>{{ report?.contract_filename }}</h2>
        <p class="share-meta" v-if="report?.completed_at">
          审查完成于 {{ new Date(report.completed_at).toLocaleString('zh-CN') }}
          <span v-if="report.base_version !== null"> · 对比基准 v{{ report.base_version }}</span>
        </p>
      </div>

      <!-- 风险统计 -->
      <div class="stat-strip">
        <div class="stat-cell total">
          <span class="num">{{ findings.length }}</span>
          <span class="label">风险总数</span>
        </div>
        <div class="stat-cell high">
          <span class="num">{{ countByLevel('high') }}</span>
          <span class="label">高风险</span>
        </div>
        <div class="stat-cell medium">
          <span class="num">{{ countByLevel('medium') }}</span>
          <span class="label">中风险</span>
        </div>
        <div class="stat-cell low">
          <span class="num">{{ countByLevel('low') }}</span>
          <span class="label">低风险</span>
        </div>
      </div>

      <!-- 版本对比摘要 -->
      <div class="diff-strip" v-if="report?.diff?.summary">
        <el-tag type="success" size="small" effect="plain">新增 {{ report.diff.summary.added }}</el-tag>
        <el-tag type="warning" size="small" effect="plain">修改 {{ report.diff.summary.modified }}</el-tag>
        <el-tag type="danger" size="small" effect="plain">删除 {{ report.diff.summary.removed }}</el-tag>
        <el-tag type="info" size="small" effect="plain">未变 {{ report.diff.summary.unchanged }}</el-tag>
        <span class="diff-hint">相对基准 v{{ report.base_version }} 的条款变更</span>
      </div>

      <!-- 风险卡片（只读） -->
      <div class="card-list">
        <RiskCard v-for="(finding, index) in findings" :key="index" :finding="finding" readonly />
        <div v-if="findings.length === 0" class="no-risk">
          <el-icon :size="36" color="#10b981"><circle-check-filled /></el-icon>
          <p>本报告未发现风险项</p>
        </div>
      </div>

      <footer class="share-foot">
        <p>本页面为只读分享内容，有效期至 {{ report ? new Date(report.expires_at).toLocaleString('zh-CN') : '' }}</p>
        <router-link to="/login" class="login-link">前往合同卫士登录查看完整功能 →</router-link>
      </footer>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Lock, CircleCloseFilled } from '@element-plus/icons-vue'
import { getSharedReport } from '@/api/review'
import RiskCard from '@/components/RiskCard.vue'
import type { Finding } from '@/types'

const props = defineProps<{
  token: string
}>()

const report = ref<Awaited<ReturnType<typeof getSharedReport>> | null>(null)
const expired = ref(false)
const findings = ref<Finding[]>([])

function countByLevel(level: string) {
  return findings.value.filter((f) => f.level === level).length
}

onMounted(async () => {
  try {
    report.value = await getSharedReport(props.token)
    findings.value = (report.value.findings || []) as Finding[]
  } catch {
    expired.value = true
  }
})
</script>

<style scoped>
.share-page {
  min-height: 100vh;
  background: linear-gradient(160deg, #eef2ff 0%, #f8fafc 45%, #f5f3ff 100%);
}

.share-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 28px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid #e2e8f0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
}

.brand-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  color: #fff;
}

.brand-name {
  font-size: 15.5px;
  font-weight: 700;
  color: #1e293b;
}

.readonly-tag {
  font-size: 11.5px;
  font-weight: 600;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  border-radius: 20px;
  padding: 4px 12px;
}

.expired-box {
  max-width: 420px;
  margin: 16vh auto 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 44px 36px;
  text-align: center;
}

.expired-box h3 {
  margin: 4px 0 0;
  font-size: 16px;
  color: #1e293b;
}

.expired-box p {
  font-size: 13px;
  color: #64748b;
  margin: 0;
}

.share-body {
  max-width: 880px;
  margin: 0 auto;
  padding: 26px 20px 50px;
}

.share-title h2 {
  margin: 0 0 6px;
  font-size: 20px;
  color: #1e293b;
  word-break: break-all;
}

.share-meta {
  margin: 0 0 18px;
  font-size: 12.5px;
  color: #64748b;
}

.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-cell {
  display: flex;
  flex-direction: column;
  padding: 14px 16px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
}

.stat-cell .num {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-cell .label {
  font-size: 11.5px;
  color: #64748b;
  margin-top: 2px;
}

.stat-cell.total .num { color: #4f46e5; }
.stat-cell.high .num { color: #ef4444; }
.stat-cell.medium .num { color: #f59e0b; }
.stat-cell.low .num { color: #10b981; }

.diff-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px 16px;
  margin-bottom: 16px;
}

.diff-hint {
  font-size: 12px;
  color: #64748b;
}

.card-list {
  display: flex;
  flex-direction: column;
}

.no-risk {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  color: #64748b;
  font-size: 13px;
}

.share-foot {
  margin-top: 26px;
  text-align: center;
}

.share-foot p {
  font-size: 12px;
  color: #94a3b8;
  margin: 0 0 4px;
}

.login-link {
  font-size: 12.5px;
  color: #4f46e5;
  text-decoration: none;
}

.login-link:hover {
  text-decoration: underline;
}

@media (max-width: 640px) {
  .stat-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
