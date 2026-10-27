<template>
  <div class="report-page">
    <!-- 审查中 -->
    <div class="progress-area" v-if="isRunning">
      <div class="progress-inner">
        <ProgressBar :phase="phase" :message="phaseMessage" :findings="findings.length" />
        <el-button class="stop-btn" round :loading="cancelling" @click="onCancelReview">
          停止审查
        </el-button>
      </div>
    </div>

    <!-- 失败 / 已取消 -->
    <div class="fail-area" v-else-if="isFailed">
      <div class="fail-card cg-card">
        <el-icon :size="44" :color="phase === 'cancelled' ? '#94a3b8' : '#ef4444'">
          <circle-close-filled />
        </el-icon>
        <h3>{{ phase === 'cancelled' ? '审查已取消' : '审查失败' }}</h3>
        <p class="fail-reason">{{ failReasonText }}</p>
        <div class="fail-actions">
          <el-button round @click="router.push('/contracts')">返回工作台</el-button>
          <el-button type="primary" round @click="onRetryReview">重新审查</el-button>
        </div>
      </div>
    </div>

    <!-- 报告主体 -->
    <div class="report-body" v-else>
      <!-- 左：PDF 原文 -->
      <div class="left-panel">
        <div class="pdf-panel-head">
          <span class="pdf-panel-title">
            <el-icon><document /></el-icon> 合同原文
          </span>
          <el-button size="small" text @click="router.push('/contracts')">
            <el-icon><back /></el-icon> 返回工作台
          </el-button>
        </div>
        <PdfViewer
          :contract-id="contractId"
          :findings="findings"
          :highlight-page="highlightPage"
          :highlight-bbox="highlightBbox"
          @select-text="onSelectText"
        />
      </div>

      <!-- 右：风险面板 -->
      <div class="right-panel">
        <!-- 概览统计 -->
        <div class="overview cg-card">
          <div class="overview-head">
            <h3>审查报告</h3>
            <div class="export-actions">
              <el-tooltip content="本机未安装 GTK 运行库，PDF 导出不可用" placement="top" :disabled="true">
                <el-button size="small" round @click="exportReport('pdf')" :disabled="true">
                  <el-icon><printer /></el-icon> PDF
                </el-button>
              </el-tooltip>
              <el-button size="small" round @click="exportMarked">
                <el-icon><edit-pen /></el-icon> 修订版
              </el-button>
              <el-button size="small" round @click="openShare">
                <el-icon><share /></el-icon> 分享
              </el-button>
              <el-button size="small" type="primary" round @click="exportReport('word')">
                <el-icon><download /></el-icon> 导出 Word
              </el-button>
            </div>
          </div>

          <div class="overview-grid">
            <!-- 数字统计 -->
            <div class="stat-list">
              <div class="stat-item">
                <span class="stat-num total">{{ findings.length }}</span>
                <span class="stat-name">风险总数</span>
              </div>
              <div class="stat-item">
                <span class="stat-num high">{{ stats?.high || countByLevel('high') }}</span>
                <span class="stat-name">高风险</span>
              </div>
              <div class="stat-item">
                <span class="stat-num medium">{{ stats?.medium || countByLevel('medium') }}</span>
                <span class="stat-name">中风险</span>
              </div>
              <div class="stat-item">
                <span class="stat-num low">{{ stats?.low || countByLevel('low') }}</span>
                <span class="stat-name">低风险</span>
              </div>
            </div>
            <!-- 环形图 -->
            <div ref="donutRef" class="donut-chart"></div>
          </div>

          <!-- 平均置信度 -->
          <div class="conf-summary" v-if="avgConfidence">
            <span>整体平均置信度</span>
            <el-progress
              :percentage="Math.round(avgConfidence * 100)"
              :stroke-width="6"
              color="#4f46e5"
              class="conf-total"
            />
          </div>

          <!-- 整改进度 -->
          <div class="rect-summary" v-if="rectification && rectification.total > 0">
            <div class="rect-head">
              <span>
                整改进度（已关闭 {{ rectification.dismissed + rectification.resolved }}/{{ rectification.total }} 项）
              </span>
              <span class="rect-rate">{{ rectification.close_rate.toFixed(2) }}%</span>
            </div>
            <el-progress
              :percentage="Math.min(rectification.close_rate, 100)"
              :stroke-width="8"
              color="#10b981"
              :show-text="false"
            />
            <p class="rect-legend" v-if="rectification.resolved || rectification.dismissed">
              已整改 {{ rectification.resolved }} · 已忽略误报 {{ rectification.dismissed }}
            </p>
          </div>

          <!-- 关键履约日期 -->
          <div class="key-dates" v-if="keyDates.length > 0">
            <div class="kd-head">
              <el-icon><calendar /></el-icon>
              <span>关键履约日期</span>
              <span class="kd-count">{{ keyDates.length }} 项</span>
            </div>
            <div class="kd-item" v-for="kd in keyDates" :key="kd.id">
              <div class="kd-date">
                <span class="kd-day">{{ formatKdDate(kd.date_value) }}</span>
                <span
                  v-if="kd.date_type === 'expiry'"
                  class="kd-countdown"
                  :class="countdownClass(kd.date_value)"
                >
                  {{ countdownText(kd.date_value) }}
                </span>
              </div>
              <div class="kd-body">
                <el-tag size="small" effect="plain" :type="kdTagType(kd.date_type)">
                  {{ kdTypeText(kd.date_type) }}
                </el-tag>
                <p class="kd-context" v-if="kd.context">{{ kd.context }}</p>
              </div>
            </div>
          </div>
        </div>

        <!-- 版本对比（双版本对比审查时展示） -->
        <div class="diff-panel cg-card" v-if="diffData?.diff?.summary">
          <div class="diff-head">
            <h4><el-icon><switch /></el-icon> 版本对比（基准 v{{ diffData.base_version }} → 当前版本）</h4>
            <div class="diff-badges">
              <el-tag type="success" size="small" effect="plain">新增 {{ diffData.diff.summary.added }}</el-tag>
              <el-tag type="warning" size="small" effect="plain">修改 {{ diffData.diff.summary.modified }}</el-tag>
              <el-tag type="danger" size="small" effect="plain">删除 {{ diffData.diff.summary.removed }}</el-tag>
              <el-tag type="info" size="small" effect="plain">未变 {{ diffData.diff.summary.unchanged }}</el-tag>
            </div>
          </div>
          <p class="diff-note" v-if="changedCount">
            本版合同相较基准共 {{ changedCount }} 处条款变更，修改引入的风险请重点关注下方标注"新增/修改"条款的风险发现。
          </p>
          <p class="diff-note" v-else>两版条款无变化，本次审查结果与基准版本一致。</p>

          <div class="diff-changes" v-if="diffData.diff.changes.length">
            <div
              v-for="(change, idx) in diffData.diff.changes.slice(0, 20)"
              :key="idx"
              class="diff-item"
              :class="change.type"
            >
              <div class="diff-item-head">
                <el-tag size="small" :type="diffTagType(change.type)">{{ diffLabel(change.type) }}</el-tag>
                <span class="diff-title">{{ change.base?.title || change.target?.title || '未命名条款' }}</span>
                <span class="diff-ratio" v-if="change.type === 'modified'">相似度 {{ Math.round((change.ratio || 0) * 100) }}%</span>
              </div>
              <div v-if="change.type === 'modified'" class="diff-pair">
                <div class="diff-side base">基准：{{ change.base?.text }}</div>
                <div class="diff-side target">当前：{{ change.target?.text }}</div>
              </div>
              <div v-else-if="change.type === 'added'" class="diff-pair">
                <div class="diff-side target">当前新增：{{ change.target?.text }}</div>
              </div>
              <div v-else class="diff-pair">
                <div class="diff-side base">基准删除：{{ change.base?.text }}</div>
              </div>
            </div>
            <p class="diff-more" v-if="diffData.diff.changes.length > 20">
              其余 {{ diffData.diff.changes.length - 20 }} 处变更已折叠。
            </p>
          </div>
        </div>

        <!-- 风险过滤 -->
        <el-tabs v-model="levelFilter" class="risk-tabs">
          <el-tab-pane :label="`全部 (${findings.length})`" name="all" />
          <el-tab-pane :label="`高 (${countByLevel('high')})`" name="high" />
          <el-tab-pane :label="`中 (${countByLevel('medium')})`" name="medium" />
          <el-tab-pane :label="`低 (${countByLevel('low')})`" name="low" />
        </el-tabs>

        <!-- 风险卡片 -->
        <div class="risk-list">
          <RiskCard
            v-for="(finding, index) in filteredFindings"
            :key="index"
            :finding="finding"
            @highlight="onHighlight"
            @update-status="onFindingStatus"
            @ask="onAskClause"
          />
          <div v-if="filteredFindings.length === 0" class="no-risk">
            <el-icon :size="36" color="#10b981"><circle-check-filled /></el-icon>
            <p>该等级下暂无风险发现</p>
          </div>
        </div>

        <!-- 对话追问 -->
        <ChatPanel
          :contract-id="contractId"
          :selected-text="selectedText"
          @clear-selected="selectedText = ''"
        />
      </div>
    </div>

    <!-- 分享弹窗 -->
    <el-dialog v-model="shareVisible" title="分享审查报告" width="480px" align-center>
      <p class="share-tip">任何获得链接的人在有效期内均可免登录只读查看本报告；重新生成链接后，旧链接立即失效。</p>
      <div class="share-row">
        <el-input :model-value="shareUrl" readonly placeholder="生成中..." />
        <el-button type="primary" :disabled="!shareUrl" @click="copyShare">复制链接</el-button>
      </div>
      <p class="share-expire" v-if="shareExpiresAt">有效期至 {{ shareExpiresAt }}</p>
    </el-dialog>

    <!-- 划词追问抽屉 -->
    <AskDrawer v-model="askVisible" :session-id="sessionNum" :finding="askFinding" :selected-text="askText" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import {
  Document, Back, Printer, Download, CircleCheckFilled, CircleCloseFilled, Switch, Share, Calendar, EditPen,
} from '@element-plus/icons-vue'
import { getKeyDates } from '@/api/contracts'
import type { KeyDate } from '@/api/contracts'
import { createShareLink, getReviewResult, getFindings, getReviewStreamUrl, getReviewDiff, getRectification, updateFindingStatus, exportReport as exportReportApi, exportMarkedReport as exportMarkedReportApi, cancelReview, startReview } from '@/api/review'
import ProgressBar from '@/components/ProgressBar.vue'
import PdfViewer from '@/components/PdfViewer.vue'
import RiskCard from '@/components/RiskCard.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import AskDrawer from '@/components/AskDrawer.vue'
import type { Rectification } from '@/api/review'
import type { Finding, FindingStatus } from '@/types'

const props = defineProps<{
  contractId: string
  sessionId: string
}>()

const router = useRouter()
const contractId = Number(props.contractId)
// 会话 id 可在「重新审查」时经路由参数变化更新（同路由组件复用，onMounted 不会重跑）
let sessionId = Number(props.sessionId)
// 追问抽屉等模板绑定需要响应 props.sessionId 变化（let 非响应式）
const sessionNum = computed(() => Number(props.sessionId))

const loading = ref(true)
const phase = ref('pending')
const phaseMessage = ref('准备开始审查...')
const findings = ref<Finding[]>([])
const stats = ref<Record<string, number> | null>(null)
const selectedText = ref('')
const highlightPage = ref<number | undefined>(undefined)
const highlightBbox = ref<{ x: number; y: number; w: number; h: number } | null>(null)
const levelFilter = ref('all')
const donutRef = ref<HTMLElement>()

let chart: echarts.ECharts | null = null

const isCompleted = computed(() => phase.value === 'completed' || phase.value === 'final')
const isFailed = computed(() => phase.value === 'failed' || phase.value === 'cancelled')
const isRunning = computed(() => !isCompleted.value && !isFailed.value)

// ---------- 失败原因差异化文案 + 中途取消 ----------
const failReason = ref<string | null>(null)
const cancelling = ref(false)

const FAIL_TEXT: Record<string, string> = {
  cancelled: '您已手动停止本次审查，可随时重新发起。',
  timeout: '审查超时：模型服务响应过慢或超出单次任务时限，请稍后重试。',
  quota: '模型服务额度不足，请检查服务商套餐或更换 API Key。',
  permission: '模型服务鉴权失败，请检查 LLM_API_KEY 配置是否有效。',
  provider: '模型服务暂时不可用，系统已自动重试仍失败，请稍后再试。',
  internal: '系统内部错误，请稍后重试；若持续出现请联系管理员。',
}

const failReasonText = computed(
  () => FAIL_TEXT[failReason.value || ''] || '审查未完成，请稍后重试。'
)

async function onCancelReview() {
  cancelling.value = true
  try {
    await cancelReview(sessionId)
    phase.value = 'cancelled'
    failReason.value = 'cancelled'
    phaseMessage.value = '审查已取消'
    eventSource?.close()
    stopPolling()
    ElMessage.success('已停止本次审查')
  } catch {
    // request 拦截器已弹出后端错误提示
  } finally {
    cancelling.value = false
  }
}

async function onRetryReview() {
  try {
    const res = await startReview(contractId)
    router.push(`/report/${contractId}/${res.review_session_id}`)
  } catch {
    // request 拦截器已弹出后端错误提示（含 402 会员弹窗）
  }
}

const filteredFindings = computed(() => {
  if (levelFilter.value === 'all') return findings.value
  return findings.value.filter((f) => f.level === levelFilter.value)
})

const avgConfidence = computed(() => {
  if (findings.value.length === 0) return 0
  const sum = findings.value.reduce((acc, f) => acc + (f.confidence || 0), 0)
  return sum / findings.value.length
})

function countByLevel(level: string) {
  return findings.value.filter((f) => f.level === level).length
}

function renderDonut() {
  if (!donutRef.value) return
  if (!chart) chart = echarts.init(donutRef.value)
  const high = countByLevel('high')
  const medium = countByLevel('medium')
  const low = countByLevel('low')
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条 ({d}%)' },
    legend: { show: false },
    series: [
      {
        type: 'pie',
        radius: ['58%', '82%'],
        center: ['50%', '50%'],
        label: { show: false },
        itemStyle: { borderRadius: 4, borderWidth: 2, borderColor: '#fff' },
        data: [
          { value: high, name: '高风险', itemStyle: { color: '#ef4444' } },
          { value: medium, name: '中风险', itemStyle: { color: '#f59e0b' } },
          { value: low, name: '低风险', itemStyle: { color: '#10b981' } },
        ].filter((d) => d.value > 0),
      },
    ],
    graphic: [
      {
        type: 'text',
        left: 'center',
        top: '42%',
        style: {
          text: String(findings.value.length),
          fontSize: 22,
          fontWeight: 700,
          fill: '#1e293b',
          textAlign: 'center',
        },
      },
      {
        type: 'text',
        left: 'center',
        top: '58%',
        style: { text: '风险总数', fontSize: 11, fill: '#94a3b8', textAlign: 'center' },
      },
    ],
  })
}

let eventSource: EventSource | null = null
let pollTimer: number | null = null

// SSE 断连兜底：轮询结果直到审查完成（审查约需 1-2 分钟，SSE 中途断开不能卡死页面）
function startPolling() {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(async () => {
    await loadResult()
    if (isCompleted.value || isFailed.value) stopPolling()
  }, 5000)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function connectSSE() {
  eventSource = new EventSource(getReviewStreamUrl(sessionId))
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.event === 'phase') {
        phase.value = data.data.phase
        phaseMessage.value = data.data.message || data.data.phase
        // 取消/失败为终态：断开 SSE 并拉取最新结果
        if (data.data.phase === 'cancelled' || data.data.phase === 'failed') {
          eventSource?.close()
          stopPolling()
          loadResult()
        }
      } else if (data.event === 'finding_added') {
        if (data.data) {
          findings.value.push(data.data)
        }
      } else if (data.event === 'completed') {
        phase.value = 'completed'
        eventSource?.close()
        loadResult()
      }
    } catch (e) {
      // 忽略非 JSON 数据
    }
  }
  eventSource.onerror = () => {
    eventSource?.close()
    if (!isCompleted.value) startPolling()
  }
}

async function loadResult() {
  try {
    const result = await getReviewResult(sessionId)
    phase.value = result.status
    failReason.value = result.fail_reason || null
    phaseMessage.value = isCompleted.value
      ? '审查完成'
      : result.status === 'cancelled'
        ? '审查已取消'
        : result.status === 'failed'
          ? '审查失败'
          : '审查进行中...'
    findings.value = result.findings || []
    stats.value = result.stats || null
    // 审查完成时才拉取 diff 与整改状态（对比审查在审查结束后才写入 diff_summary）
    if (isCompleted.value) {
      await mergeFindingStatuses()
      await loadRectification()
      await loadDiff()
      await loadKeyDates()
    }
  } catch (e) {
    ElMessage.error('加载审查结果失败')
  } finally {
    loading.value = false
    await nextTick()
    renderDonut()
  }
}

// ---------- 整改跟踪 ----------
const rectification = ref<Rectification | null>(null)

// 细粒度 findings 表按 id 排序后与 session.findings 顺序一致，按序合并出 id/状态供整改操作
async function mergeFindingStatuses() {
  try {
    const rows = await getFindings(sessionId)
    rows.forEach((row, i) => {
      const target = findings.value[i]
      if (target) {
        target.id = row.id
        target.status = row.status
        target.resolution_note = row.resolution_note
        target.resolved_at = row.resolved_at
      }
    })
  } catch {
    // 状态合并不影响报告展示
  }
}

async function loadRectification() {
  try {
    rectification.value = await getRectification(sessionId)
  } catch {
    rectification.value = null
  }
}

async function onFindingStatus(payload: { finding: Finding; status: FindingStatus; note?: string }) {
  if (!payload.finding.id) return
  try {
    const res = await updateFindingStatus(payload.finding.id, payload.status, payload.note)
    payload.finding.status = res.status as FindingStatus
    payload.finding.resolution_note = res.resolution_note
    payload.finding.resolved_at = res.resolved_at
    const msgMap: Record<string, string> = {
      resolved: '已标记整改完成',
      dismissed: '已忽略该项',
      active: '已恢复待处理',
      confirmed: '已确认该项',
    }
    ElMessage.success(msgMap[res.status] || '状态已更新')
    await loadRectification()
  } catch (e) {
    // request 拦截器已弹出后端错误提示
  }
}

// ---------- 版本对比数据 ----------
const diffData = ref<Awaited<ReturnType<typeof getReviewDiff>> | null>(null)

const changedCount = computed(() => {
  const s = diffData.value?.diff?.summary
  if (!s) return 0
  return s.added + s.removed + s.modified
})

function diffTagType(type: string) {
  if (type === 'added') return 'success'
  if (type === 'removed') return 'danger'
  return 'warning'
}

function diffLabel(type: string) {
  if (type === 'added') return '新增'
  if (type === 'removed') return '删除'
  return '修改'
}

async function loadDiff() {
  try {
    const res = await getReviewDiff(sessionId)
    if (res.base_version !== null && res.diff) {
      diffData.value = res
    }
  } catch {
    // 普通审查无 diff，静默处理
  }
}

function onSelectText(text: string) {
  selectedText.value = text
}

function onHighlight(payload: { page: number; bbox: any }) {
  highlightPage.value = payload.page
  highlightBbox.value = payload.bbox
}

async function exportReport(format: 'pdf' | 'word') {
  try {
    const blob = await exportReportApi(sessionId, format)
    downloadFile(blob, `report_${sessionId}.${format}`)
    ElMessage.success('报告导出成功')
  } catch (e) {
    // request 拦截器已弹出后端错误提示
  }
}

async function exportMarked() {
  try {
    const blob = await exportMarkedReportApi(sessionId)
    downloadFile(blob, `marked_report_${sessionId}.docx`)
    ElMessage.success('修订版报告导出成功')
  } catch (e) {
    // request 拦截器已弹出后端错误提示
  }
}

function downloadFile(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(new Blob([blob]))
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click()
  link.remove()
}

// ---------- 划词追问 ----------
const askVisible = ref(false)
const askFinding = ref<Finding | null>(null)
const askText = ref('')

function onAskClause(payload: { finding: Finding; selectedText: string }) {
  askFinding.value = payload.finding
  askText.value = payload.selectedText
  askVisible.value = true
}

// ---------- 关键履约日期 ----------
const keyDates = ref<KeyDate[]>([])

async function loadKeyDates() {
  try {
    keyDates.value = await getKeyDates(contractId)
  } catch {
    keyDates.value = []
  }
}

function kdTypeText(t: string) {
  const map: Record<string, string> = {
    signing: '签订', effective: '生效', expiry: '到期',
    payment: '付款', delivery: '交付', other: '其他',
  }
  return map[t] || t
}

function kdTagType(t: string) {
  const map: Record<string, 'primary' | 'success' | 'danger' | 'warning' | 'info'> = {
    signing: 'primary', effective: 'success', expiry: 'danger',
    payment: 'warning', delivery: 'info', other: 'info',
  }
  return map[t] || 'info'
}

function formatKdDate(d: string) {
  return new Date(`${d}T00:00:00`).toLocaleDateString('zh-CN')
}

function daysLeft(d: string) {
  const diff = new Date(`${d}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()
  return Math.round(diff / 86400000)
}

function countdownText(d: string) {
  const n = daysLeft(d)
  if (n < 0) return '已到期'
  if (n === 0) return '今天到期'
  return `${n} 天后到期`
}

function countdownClass(d: string) {
  const n = daysLeft(d)
  if (n < 0) return 'expired'
  if (n <= 7) return 'urgent'
  return 'normal'
}

// ---------- 报告分享 ----------
const shareVisible = ref(false)
const shareUrl = ref('')
const shareExpiresAt = ref('')

async function openShare() {
  shareVisible.value = true
  shareUrl.value = ''
  shareExpiresAt.value = ''
  try {
    const info = await createShareLink(sessionId)
    shareUrl.value = `${window.location.origin}${info.url}`
    shareExpiresAt.value = new Date(info.expires_at).toLocaleString('zh-CN')
  } catch (e) {
    shareVisible.value = false
  }
}

async function copyShare() {
  try {
    await navigator.clipboard.writeText(shareUrl.value)
    ElMessage.success('链接已复制')
  } catch {
    // 剪贴板不可用时降级为手动选择
    ElMessage.info('请手动复制输入框中的链接')
  }
}

onMounted(() => {
  connectSSE()
  loadResult()
})

// 「重新审查」跳转新会话时同路由组件被复用，需监听参数变化重置状态重开会话
watch(
  () => props.sessionId,
  (nv) => {
    const sid = Number(nv)
    if (!sid || sid === sessionId) return
    sessionId = sid
    eventSource?.close()
    stopPolling()
    phase.value = 'pending'
    phaseMessage.value = '准备开始审查...'
    findings.value = []
    stats.value = null
    failReason.value = null
    rectification.value = null
    diffData.value = null
    levelFilter.value = 'all'
    loading.value = true
    // 旧图表绑定的 DOM 已随报告区卸载，释放后重进报告页时可重新 init
    chart?.dispose()
    chart = null
    connectSSE()
    loadResult()
  }
)

onUnmounted(() => {
  eventSource?.close()
  stopPolling()
  chart?.dispose()
})
</script>

<style scoped>
.report-page {
  height: calc(100vh - 104px);
  display: flex;
  flex-direction: column;
}

/* ---------- 版本对比面板 ---------- */
.diff-panel {
  padding: 16px 18px;
  margin-bottom: 14px;
}

.diff-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.diff-head h4 {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 14px;
  color: var(--cg-text);
}

.diff-head .el-icon {
  color: var(--cg-primary);
}

.diff-badges {
  display: flex;
  gap: 6px;
}

.diff-note {
  font-size: 12.5px;
  color: var(--cg-text-muted);
  margin: 0 0 10px;
  line-height: 1.6;
}

.diff-changes {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.diff-item {
  border: 1px solid var(--cg-border);
  border-left-width: 3px;
  border-radius: 8px;
  padding: 10px 12px;
}

.diff-item.modified {
  border-left-color: #f59e0b;
}

.diff-item.added {
  border-left-color: #10b981;
}

.diff-item.removed {
  border-left-color: #ef4444;
}

.diff-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.diff-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--cg-text);
}

.diff-ratio {
  font-size: 11px;
  color: var(--cg-text-muted);
}

.diff-pair {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.diff-side {
  font-size: 12px;
  line-height: 1.6;
  padding: 6px 8px;
  border-radius: 6px;
  color: var(--cg-text-secondary);
}

.diff-side.base {
  background: #fef2f2;
  color: #7f1d1d;
}

.diff-side.target {
  background: #ecfdf5;
  color: #064e3b;
}

.diff-more {
  font-size: 12px;
  color: var(--cg-text-muted);
  margin: 4px 0 0;
}

.progress-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.progress-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}

.stop-btn {
  margin-top: -6px;
}

/* 失败 / 已取消卡片 */
.fail-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.fail-card {
  width: min(480px, 90vw);
  padding: 44px 36px 38px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.fail-card h3 {
  margin: 16px 0 0;
  font-size: 19px;
  font-weight: 700;
  color: var(--cg-text);
}

.fail-reason {
  margin: 10px 0 24px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--cg-text-muted);
}

.fail-actions {
  display: flex;
  gap: 10px;
}

.report-body {
  flex: 1;
  display: flex;
  gap: 14px;
  min-height: 0;
}

/* 左侧 PDF */
.left-panel {
  flex: 1.5;
  min-width: 480px;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid var(--cg-border);
  border-radius: var(--cg-radius);
  overflow: hidden;
}

.pdf-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--cg-border);
  background: #fbfcfe;
  flex-shrink: 0;
}

.pdf-panel-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--cg-text-secondary);
}

.left-panel :deep(.pdf-viewer) {
  flex: 1;
  min-height: 0;
}

/* 右侧面板 */
.right-panel {
  flex: 1;
  min-width: 430px;
  max-width: 520px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0;
  padding-right: 2px;
}

/* 概览卡 */
.overview {
  padding: 16px 18px;
  margin-bottom: 12px;
}

.overview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.overview-head h3 {
  font-size: 16px;
  font-weight: 700;
}

.export-actions {
  display: flex;
  gap: 6px;
}

.overview-grid {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stat-list {
  flex: 1.3;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
}

.stat-num {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-num.total { color: var(--cg-primary); }
.stat-num.high { color: #ef4444; }
.stat-num.medium { color: #f59e0b; }
.stat-num.low { color: #10b981; }

.stat-name {
  font-size: 11px;
  color: var(--cg-text-muted);
  margin-top: 2px;
}

.donut-chart {
  flex: 1;
  height: 132px;
  min-width: 130px;
}

.conf-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  font-size: 12px;
  color: var(--cg-text-muted);
}

.conf-total {
  flex: 1;
}

.conf-total :deep(.el-progress__text) {
  font-size: 12px !important;
  font-weight: 700;
  color: var(--cg-primary);
}

/* 整改进度 */
.rect-summary {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--cg-border);
}

.rect-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--cg-text-muted);
  margin-bottom: 6px;
}

.rect-rate {
  font-size: 13px;
  font-weight: 700;
  color: #059669;
}

.rect-legend {
  font-size: 11px;
  color: var(--cg-text-muted);
  margin: 6px 0 0;
}

/* 关键履约日期 */
.key-dates {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--cg-border);
}

.kd-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--cg-text-secondary);
  margin-bottom: 8px;
}

.kd-count {
  font-weight: 400;
  font-size: 11px;
  color: var(--cg-text-muted);
}

.kd-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 7px 0;
}

.kd-item + .kd-item {
  border-top: 1px dashed var(--cg-border);
}

.kd-date {
  display: flex;
  flex-direction: column;
  min-width: 96px;
  flex-shrink: 0;
}

.kd-day {
  font-size: 13px;
  font-weight: 700;
  color: var(--cg-text-primary);
  font-variant-numeric: tabular-nums;
}

.kd-countdown {
  font-size: 10.5px;
  font-weight: 700;
  margin-top: 1px;
}

.kd-countdown.urgent {
  color: #ef4444;
}

.kd-countdown.normal {
  color: #f59e0b;
}

.kd-countdown.expired {
  color: #94a3b8;
}

.kd-body {
  flex: 1;
  min-width: 0;
}

.kd-context {
  font-size: 11.5px;
  color: var(--cg-text-muted);
  line-height: 1.5;
  margin: 4px 0 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 分享弹窗 */
.share-tip {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--cg-text-secondary);
  margin: 0 0 12px;
}

.share-row {
  display: flex;
  gap: 8px;
}

.share-expire {
  font-size: 11.5px;
  color: var(--cg-text-muted);
  margin: 8px 0 0;
}

/* 过滤 tabs */
.risk-tabs {
  flex-shrink: 0;
}

.risk-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}

.risk-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
}

/* 卡片列表 */
.risk-list {
  flex: 1;
}

.no-risk {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 0;
  color: var(--cg-text-muted);
  font-size: 13px;
}

@media (max-width: 1100px) {
  .report-body {
    flex-direction: column;
  }
  .left-panel {
    min-width: 0;
    height: 60vh;
  }
  .right-panel {
    max-width: none;
  }
}
</style>
