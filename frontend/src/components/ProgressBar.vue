<template>
  <div class="progress-panel cg-card">
    <!-- 顶部动画区 -->
    <div class="pulse-area">
      <div class="pulse-ring r1"></div>
      <div class="pulse-ring r2"></div>
      <div class="core-icon">
        <el-icon :size="30"><data-analysis /></el-icon>
      </div>
    </div>

    <h3 class="panel-title">{{ phaseText }}</h3>
    <p class="panel-message">{{ message }}</p>

    <!-- 阶段时间线 -->
    <div class="phase-timeline">
      <div
        v-for="(p, idx) in phaseList"
        :key="p.key"
        class="phase-step"
        :class="{ done: currentIdx > idx, active: currentIdx === idx }"
      >
        <div class="step-marker">
          <el-icon v-if="currentIdx > idx" :size="11"><check /></el-icon>
          <span v-else>{{ idx + 1 }}</span>
        </div>
        <span class="step-name">{{ p.label }}</span>
        <div class="step-line" v-if="idx < phaseList.length - 1"></div>
      </div>
    </div>

    <!-- 进度条 -->
    <el-progress
      :percentage="percentage"
      :stroke-width="8"
      :show-text="false"
      striped
      striped-flow
      class="main-progress"
    />

    <!-- 实时发现 -->
    <transition name="page-fade">
      <div v-if="findings > 0" class="live-findings">
        <span class="live-dot"></span>
        已发现 <strong>{{ findings }}</strong> 条风险发现，正在继续分析…
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { DataAnalysis, Check } from '@element-plus/icons-vue'

const props = defineProps<{
  phase: string
  message: string
  findings: number
}>()

const phaseList = [
  { key: 'route', label: '路由分配' },
  { key: 'preload', label: '上下文预载' },
  { key: 'execute', label: '并行审查' },
  { key: 'merge_link', label: '合并关联' },
  { key: 'legal_verify', label: '法条验证' },
  { key: 'debate', label: '辩论仲裁' },
  { key: 'triage', label: '结果分流' },
]

const phaseText = computed(() => {
  const map: Record<string, string> = {
    pending: '排队等待中',
    running: '审查进行中',
    completed: '审查完成',
    final: '审查完成',
    failed: '审查失败',
    cancelled: '已取消',
  }
  return map[props.phase] || '审查进行中'
})

const currentIdx = computed(() => {
  if (props.phase === 'completed' || props.phase === 'final') return phaseList.length
  if (props.phase === 'pending') return -1
  const idx = phaseList.findIndex((p) => p.key === props.phase)
  return idx >= 0 ? idx : 1 // running 默认显示在并行审查
})

const percentage = computed(() => {
  const map: Record<string, number> = {
    pending: 6,
    running: 30,
    route: 12,
    preload: 22,
    execute: 45,
    merge_link: 66,
    legal_verify: 78,
    debate: 88,
    triage: 95,
    completed: 100,
    final: 100,
  }
  return map[props.phase] || 30
})
</script>

<style scoped>
.progress-panel {
  width: min(640px, 92vw);
  padding: 36px 32px 30px;
  text-align: center;
}

/* 脉冲动画 */
.pulse-area {
  position: relative;
  width: 84px;
  height: 84px;
  margin: 0 auto 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pulse-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid rgba(79, 70, 229, 0.35);
  animation: pulse 2.2s ease-out infinite;
}

.pulse-ring.r2 {
  animation-delay: 1.1s;
}

@keyframes pulse {
  0% { transform: scale(0.7); opacity: 1; }
  100% { transform: scale(1.5); opacity: 0; }
}

.core-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--cg-gradient);
  color: #fff;
  box-shadow: 0 8px 24px rgba(79, 70, 229, 0.35);
}

.panel-title {
  font-size: 19px;
  font-weight: 700;
  color: var(--cg-text);
}

.panel-message {
  margin: 8px 0 24px;
  font-size: 13px;
  color: var(--cg-text-muted);
}

/* 阶段时间线 */
.phase-timeline {
  display: flex;
  align-items: flex-start;
  margin-bottom: 26px;
}

.phase-step {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
}

.step-marker {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  background: #e2e8f0;
  color: #94a3b8;
  z-index: 1;
  transition: all 0.3s ease;
}

.phase-step.done .step-marker {
  background: var(--cg-success);
  color: #fff;
}

.phase-step.active .step-marker {
  background: var(--cg-gradient);
  color: #fff;
  box-shadow: 0 0 0 5px rgba(79, 70, 229, 0.15);
  animation: glow 1.6s ease-in-out infinite;
}

@keyframes glow {
  0%, 100% { box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.12); }
  50% { box-shadow: 0 0 0 8px rgba(79, 70, 229, 0.2); }
}

.step-name {
  margin-top: 8px;
  font-size: 11px;
  color: var(--cg-text-muted);
  white-space: nowrap;
}

.phase-step.active .step-name {
  color: var(--cg-primary);
  font-weight: 700;
}

.phase-step.done .step-name {
  color: var(--cg-text-secondary);
}

.step-line {
  position: absolute;
  top: 12px;
  left: calc(50% + 16px);
  right: calc(-50% + 16px);
  height: 2px;
  background: #e2e8f0;
}

.phase-step.done .step-line {
  background: var(--cg-success);
}

/* 进度条 */
.main-progress {
  margin-bottom: 8px;
}

.main-progress :deep(.el-progress-bar__outer) {
  background: #eef2f7;
}

/* 实时发现 */
.live-findings {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--cg-text-secondary);
  background: #fff7ed;
  border: 1px solid #fed7aa;
  padding: 7px 16px;
  border-radius: 20px;
}

.live-findings strong {
  color: #ea580c;
  font-size: 15px;
}

.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f97316;
  animation: blink 1.2s ease-in-out infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}
</style>
