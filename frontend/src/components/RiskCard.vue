<template>
  <div class="risk-card" :class="'level-' + finding.level">
    <div class="card-strip"></div>

    <div class="card-body">
      <!-- 头部 -->
      <div class="card-head">
        <div class="head-left">
          <span class="level-dot"></span>
          <span class="risk-type" :title="finding.risk_type">{{ finding.risk_type }}</span>
        </div>
        <div class="head-right">
          <span v-if="statusMeta" class="status-badge" :class="statusMeta.cls">{{ statusMeta.text }}</span>
          <span class="level-badge">{{ levelText }}</span>
        </div>
      </div>

      <!-- 条款 -->
      <div
        class="clause-box"
        v-if="finding.clause_text"
        ref="clauseRef"
        @mousedown="hideBubble"
        @mouseup="onClauseMouseUp"
      >
        <el-icon :size="13"><document /></el-icon>
        <span class="clause-text">{{ finding.clause_text }}</span>
        <span
          v-if="bubble"
          class="ask-bubble"
          :style="{ left: bubble.x + 'px', top: bubble.y + 'px' }"
          @mousedown.stop.prevent
          @click="triggerAsk"
        >
          追问
        </span>
      </div>
      <div class="clause-box missing" v-else>
        <el-icon :size="13"><warning /></el-icon>
        <span class="clause-text">缺失条款 —— 合同中未找到相关约定</span>
      </div>

      <!-- 风险说明 -->
      <p class="reason">{{ finding.reason }}</p>

      <!-- 法条依据 -->
      <div class="law-refs" v-if="finding.law_refs?.length">
        <el-tag
          v-for="law in finding.law_refs"
          :key="law"
          size="small"
          effect="plain"
          type="info"
          class="law-tag"
        >
          <el-icon :size="11"><reading /></el-icon>
          {{ law }}
        </el-tag>
      </div>

      <!-- 置信度 -->
      <div class="confidence-row">
        <span class="conf-label">AI 置信度</span>
        <el-progress
          :percentage="Math.round(finding.confidence * 100)"
          :stroke-width="6"
          :color="confColor"
          class="conf-bar"
        />
      </div>

      <!-- 建议折叠 -->
      <el-collapse v-if="finding.suggestion?.revised_text" class="suggestion-box">
        <el-collapse-item name="s">
          <template #title>
            <span class="sugg-title">
              <el-icon><edit-pen /></el-icon>
              查看修改建议
            </span>
          </template>
          <div class="sugg-body">
            <div class="sugg-row" v-if="finding.suggestion.original_text">
              <span class="sugg-label">原文</span>
              <p>{{ finding.suggestion.original_text }}</p>
            </div>
            <div class="sugg-row revised">
              <span class="sugg-label">建议改为</span>
              <p>{{ finding.suggestion.revised_text }}</p>
            </div>
            <div class="sugg-row" v-if="finding.suggestion.rationale">
              <span class="sugg-label">理由</span>
              <p>{{ finding.suggestion.rationale }}</p>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <!-- 底部操作 -->
      <div class="card-foot" v-if="(!readonly && finding.id) || (!readonly && finding.bbox && finding.page)">
        <div class="foot-actions" v-if="!readonly && finding.id">
          <template v-if="finding.status === 'resolved'">
            <span class="resolved-note" v-if="finding.resolution_note" :title="finding.resolution_note">
              {{ finding.resolution_note }}
            </span>
            <el-button size="small" text @click="emitStatus('active')">恢复待处理</el-button>
          </template>
          <template v-else-if="finding.status === 'dismissed'">
            <span class="resolved-note" v-if="finding.resolution_note" :title="finding.resolution_note">
              {{ finding.resolution_note }}
            </span>
            <el-button size="small" text @click="emitStatus('active')">恢复待处理</el-button>
          </template>
          <template v-else>
            <el-button size="small" type="success" plain round @click="markResolved">
              <el-icon><circle-check /></el-icon>
              标记已整改
            </el-button>
            <el-button v-if="finding.status === 'active'" size="small" text type="info" @click="emitStatus('dismissed')">
              忽略
            </el-button>
          </template>
        </div>
        <el-button v-if="!readonly && finding.bbox && finding.page" size="small" text type="primary" @click="highlight">
          <el-icon><position /></el-icon>
          定位原文（第 {{ finding.page }} 页）
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Position, Document, Warning, Reading, EditPen, CircleCheck } from '@element-plus/icons-vue'
import type { Finding, FindingStatus } from '@/types'

const props = withDefaults(
  defineProps<{
    finding: Finding
    readonly?: boolean
  }>(),
  { readonly: false }
)

const emit = defineEmits<{
  (e: 'highlight', payload: { page: number; bbox: any }): void
  (e: 'update-status', payload: { finding: Finding; status: FindingStatus; note?: string }): void
  (e: 'ask', payload: { finding: Finding; selectedText: string }): void
}>()

// ---------- 条款划词追问气泡 ----------
const clauseRef = ref<HTMLElement>()
const bubble = ref<{ x: number; y: number; text: string } | null>(null)

function hideBubble() {
  bubble.value = null
}

function onClauseMouseUp() {
  const sel = window.getSelection()
  const text = sel?.toString().trim() || ''
  if (!sel || sel.isCollapsed || text.length < 2 || !clauseRef.value) {
    bubble.value = null
    return
  }
  const rect = sel.getRangeAt(0).getBoundingClientRect()
  const boxRect = clauseRef.value.getBoundingClientRect()
  bubble.value = {
    x: Math.max(rect.left - boxRect.left, 0),
    y: rect.bottom - boxRect.top + 4,
    text,
  }
}

function triggerAsk() {
  if (!bubble.value) return
  emit('ask', { finding: props.finding, selectedText: bubble.value.text })
  bubble.value = null
  window.getSelection()?.removeAllRanges()
}

const levelText = computed(() => {
  const map: Record<string, string> = {
    high: '高风险',
    medium: '中风险',
    low: '低风险',
  }
  return map[props.finding.level] || props.finding.level
})

const statusMeta = computed(() => {
  const map: Record<string, { text: string; cls: string }> = {
    resolved: { text: '已整改', cls: 'resolved' },
    dismissed: { text: '已忽略', cls: 'dismissed' },
    confirmed: { text: '已确认', cls: 'confirmed' },
  }
  return props.finding.status ? map[props.finding.status] || null : null
})

const confColor = computed(() => {
  const lv = props.finding.level
  if (lv === 'high') return '#ef4444'
  if (lv === 'medium') return '#f59e0b'
  return '#10b981'
})

function highlight() {
  if (props.finding.bbox && props.finding.page) {
    emit('highlight', { page: props.finding.page, bbox: props.finding.bbox })
  }
}

function emitStatus(status: FindingStatus, note?: string) {
  emit('update-status', { finding: props.finding, status, note })
}

function markResolved() {
  ElMessageBox.prompt('填写整改说明，便于后续跟踪（可留空）', '标记已整改', {
    confirmButtonText: '确认整改',
    cancelButtonText: '取消',
    inputPlaceholder: '整改说明（可选）',
  })
    .then(({ value }) => emitStatus('resolved', value || undefined))
    .catch(() => {
      // 用户取消
    })
}
</script>

<style scoped>
.risk-card {
  position: relative;
  display: flex;
  background: #fff;
  border: 1px solid var(--cg-border);
  border-radius: var(--cg-radius);
  overflow: hidden;
  margin-bottom: 14px;
  box-shadow: var(--cg-shadow-sm);
  transition: box-shadow 0.22s ease, transform 0.22s ease;
}

.risk-card:hover {
  box-shadow: var(--cg-shadow);
  transform: translateY(-2px);
}

.card-strip {
  width: 4px;
  flex-shrink: 0;
}

.level-high .card-strip {
  background: linear-gradient(180deg, #ef4444, #b91c1c);
}

.level-medium .card-strip {
  background: linear-gradient(180deg, #f59e0b, #d97706);
}

.level-low .card-strip {
  background: linear-gradient(180deg, #10b981, #059669);
}

.card-body {
  flex: 1;
  padding: 14px 16px;
  min-width: 0;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.head-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.status-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 20px;
}

.status-badge.resolved {
  color: #059669;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
}

.status-badge.dismissed {
  color: #64748b;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
}

.status-badge.confirmed {
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.level-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.level-high .level-dot {
  background: #ef4444;
  box-shadow: 0 0 0 3px #fee2e2;
}

.level-medium .level-dot {
  background: #f59e0b;
  box-shadow: 0 0 0 3px #fef3c7;
}

.level-low .level-dot {
  background: #10b981;
  box-shadow: 0 0 0 3px #d1fae5;
}

.risk-type {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--cg-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.level-badge {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 20px;
}

.level-high .level-badge {
  color: #dc2626;
  background: #fef2f2;
}

.level-medium .level-badge {
  color: #d97706;
  background: #fffbeb;
}

.level-low .level-badge {
  color: #059669;
  background: #ecfdf5;
}

/* 条款引用 */
.clause-box {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  margin-bottom: 10px;
}

.ask-bubble {
  position: absolute;
  z-index: 5;
  padding: 3px 12px;
  border-radius: 12px;
  background: #1e293b;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.25);
  transition: background 0.12s ease;
}

.ask-bubble:hover {
  background: var(--cg-primary);
}

.clause-box .el-icon {
  margin-top: 3px;
  color: var(--cg-primary);
  flex-shrink: 0;
}

.clause-box.missing {
  background: #fffbeb;
  border-color: #fde68a;
}

.clause-box.missing .el-icon {
  color: #f59e0b;
}

.clause-text {
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--cg-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.reason {
  font-size: 13px;
  line-height: 1.7;
  color: var(--cg-text);
  margin-bottom: 10px;
}

/* 法条 */
.law-refs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.law-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  background: #f8fafc;
}

/* 置信度 */
.confidence-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.conf-label {
  font-size: 11.5px;
  color: var(--cg-text-muted);
  flex-shrink: 0;
}

.conf-bar {
  flex: 1;
}

.conf-bar :deep(.el-progress__text) {
  font-size: 11px !important;
  color: var(--cg-text-muted);
}

/* 建议 */
.suggestion-box {
  border: none;
  border-top: 1px dashed var(--cg-border);
}

.suggestion-box :deep(.el-collapse-item__header) {
  border-bottom: none;
  height: 38px;
  background: transparent;
}

.suggestion-box :deep(.el-collapse-item__wrap) {
  border-bottom: none;
  background: transparent;
}

.sugg-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--cg-primary);
}

.sugg-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0 8px;
}

.sugg-row p {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--cg-text-secondary);
  margin-top: 4px;
}

.sugg-label {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  background: #f1f5f9;
  border-radius: 4px;
  padding: 2px 8px;
}

.sugg-row.revised .sugg-label {
  color: #047857;
  background: #d1fae5;
}

.sugg-row.revised p {
  color: #065f46;
}

/* 底部 */
.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-top: 1px dashed var(--cg-border);
  padding-top: 6px;
  min-height: 40px;
}

.foot-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.resolved-note {
  font-size: 11.5px;
  color: #059669;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}

.card-foot .el-button + .el-button {
  margin-left: 0;
}
</style>
