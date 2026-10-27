<template>
  <div class="dashboard-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">风险台账看板</h2>
        <p class="page-sub">{{ greeting }}，这里是你名下合同的整体风险态势</p>
      </div>
      <el-button round @click="loadAll">
        <el-icon style="margin-right: 4px"><refresh /></el-icon>
        刷新数据
      </el-button>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-grid">
      <div class="cg-card stat-card">
        <div class="stat-icon" style="background: #eef2ff; color: #4f46e5">
          <el-icon :size="22"><folder /></el-icon>
        </div>
        <div>
          <div class="stat-value">{{ summary?.contract_count ?? '-' }}</div>
          <div class="stat-label">活跃合同</div>
        </div>
      </div>
      <div class="cg-card stat-card">
        <div class="stat-icon" style="background: #eff6ff; color: #3b82f6">
          <el-icon :size="22"><data-line /></el-icon>
        </div>
        <div>
          <div class="stat-value">{{ summary?.reviews_30d ?? '-' }}</div>
          <div class="stat-label">近 30 天审查</div>
        </div>
      </div>
      <div class="cg-card stat-card">
        <div class="stat-icon" style="background: #fef2f2; color: #ef4444">
          <el-icon :size="22"><warning /></el-icon>
        </div>
        <div>
          <div class="stat-value">{{ openFindings }}</div>
          <div class="stat-label">待整改风险</div>
        </div>
      </div>
      <div class="cg-card stat-card">
        <div class="stat-icon" style="background: #ecfdf5; color: #10b981">
          <el-icon :size="22"><circle-check /></el-icon>
        </div>
        <div>
          <div class="stat-value">{{ summary ? summary.rectification.close_rate.toFixed(2) + '%' : '-' }}</div>
          <div class="stat-label">整改关闭率</div>
        </div>
      </div>
    </div>

    <!-- 图表区 -->
    <div class="chart-grid">
      <div class="cg-card chart-card">
        <h3 class="card-title">风险等级分布</h3>
        <div ref="donutRef" class="chart donut" />
      </div>
      <div class="cg-card chart-card">
        <h3 class="card-title">高频风险类型 Top 5</h3>
        <div ref="barRef" class="chart bar" />
      </div>
    </div>

    <div class="bottom-grid">
      <div class="cg-card chart-card">
        <h3 class="card-title">近 30 天审查趋势</h3>
        <div ref="trendRef" class="chart trend" />
      </div>
      <div class="cg-card chart-card">
        <div class="card-title-row">
          <h3 class="card-title">最近到期</h3>
          <el-button link type="primary" size="small" @click="router.push('/calendar')">
            履约日历
          </el-button>
        </div>
        <div v-if="!summary?.upcoming_dates.length" class="empty-tip">近期没有到期事项</div>
        <div
          v-for="item in summary?.upcoming_dates || []"
          :key="item.id"
          class="due-item"
          @click="goReport(item.contract_id, item.review_session_id)"
        >
          <span class="due-dot" :class="item.date_type" />
          <div class="due-main">
            <span class="due-filename">{{ item.filename }}</span>
            <span class="due-raw">{{ dateTypeLabel(item.date_type) }} · {{ item.raw_text }}</span>
          </div>
          <span class="due-days" :class="{ urgent: item.days_left <= 7 }">
            {{ item.days_left === 0 ? '今天' : `${item.days_left} 天` }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { Refresh, Folder, DataLine, Warning, CircleCheck } from '@element-plus/icons-vue'
import { getDashboardSummary, type DashboardSummary } from '@/api/dashboard'

const router = useRouter()
const summary = ref<DashboardSummary | null>(null)
const donutRef = ref<HTMLElement>()
const barRef = ref<HTMLElement>()
const trendRef = ref<HTMLElement>()
let donutChart: echarts.ECharts | null = null
let barChart: echarts.ECharts | null = null
let trendChart: echarts.ECharts | null = null

const openFindings = computed(() => {
  if (!summary.value) return 0
  const r = summary.value.rectification
  return r.total - r.closed
})

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const levelColors: Record<string, string> = { high: '#ef4444', medium: '#f59e0b', low: '#10b981' }

function dateTypeLabel(type: string) {
  const map: Record<string, string> = {
    expiry: '到期',
    effective: '生效',
    signing: '签署',
    payment: '付款',
    delivery: '交付',
  }
  return map[type] || '其他'
}

function goReport(contractId: number, sessionId: number) {
  if (contractId && sessionId) router.push(`/report/${contractId}/${sessionId}`)
}

async function loadAll() {
  summary.value = await getDashboardSummary()
  await nextTick()
  renderCharts()
}

function renderCharts() {
  if (!summary.value) return
  const { risk_levels, top_risk_types, review_trend } = summary.value

  // 环形图：风险等级
  if (donutRef.value) {
    if (!donutChart) donutChart = echarts.init(donutRef.value)
    const data = [
      { name: '高风险', value: risk_levels.high, itemStyle: { color: levelColors.high } },
      { name: '中风险', value: risk_levels.medium, itemStyle: { color: levelColors.medium } },
      { name: '低风险', value: risk_levels.low, itemStyle: { color: levelColors.low } },
    ].filter((d) => d.value > 0)
    donutChart.setOption(
      {
        tooltip: { trigger: 'item', formatter: '{b}: {c} 条 ({d}%)' },
        legend: { bottom: 0, icon: 'circle', itemWidth: 8, textStyle: { fontSize: 12 } },
        series: [
          {
            type: 'pie',
            radius: ['52%', '74%'],
            center: ['50%', '44%'],
            label: { show: false },
            itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
            data: data.length ? data : [{ name: '暂无风险', value: 1, itemStyle: { color: '#e2e8f0' } }],
          },
        ],
      },
      true,
    )
  }

  // 条形图：Top5 风险类型（横向，名称从下到上）
  if (barRef.value) {
    if (!barChart) barChart = echarts.init(barRef.value)
    const sorted = [...top_risk_types].reverse()
    barChart.setOption(
      {
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: 8, right: 30, top: 8, bottom: 0, containLabel: true },
        xAxis: { type: 'value', splitLine: { lineStyle: { color: '#f1f5f9' } } },
        yAxis: {
          type: 'category',
          data: sorted.map((t) => t.type),
          axisTick: { show: false },
          axisLine: { show: false },
          axisLabel: {
            width: 110,
            overflow: 'truncate',
            color: '#475569',
            fontSize: 12,
          },
        },
        series: [
          {
            type: 'bar',
            data: sorted.map((t) => t.count),
            barWidth: 14,
            itemStyle: {
              borderRadius: [0, 7, 7, 0],
              color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: '#6366f1' },
                { offset: 1, color: '#7c3aed' },
              ]),
            },
            label: { show: true, position: 'right', color: '#94a3b8', fontSize: 12 },
          },
        ],
      },
      true,
    )
  }

  // 折线：30 天趋势
  if (trendRef.value) {
    if (!trendChart) trendChart = echarts.init(trendRef.value)
    trendChart.setOption(
      {
        tooltip: { trigger: 'axis' },
        grid: { left: 8, right: 16, top: 16, bottom: 0, containLabel: true },
        xAxis: {
          type: 'category',
          data: review_trend.map((d) => d.date.slice(5)),
          boundaryGap: false,
          axisTick: { show: false },
          axisLine: { lineStyle: { color: '#e2e8f0' } },
          axisLabel: { color: '#94a3b8', fontSize: 11, interval: 6 },
        },
        yAxis: {
          type: 'value',
          minInterval: 1,
          splitLine: { lineStyle: { color: '#f1f5f9' } },
          axisLabel: { color: '#94a3b8', fontSize: 11 },
        },
        series: [
          {
            type: 'line',
            data: review_trend.map((d) => d.count),
            smooth: true,
            symbol: 'circle',
            symbolSize: 6,
            showSymbol: false,
            lineStyle: { width: 2.5, color: '#4f46e5' },
            itemStyle: { color: '#4f46e5' },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(79, 70, 229, 0.18)' },
                { offset: 1, color: 'rgba(79, 70, 229, 0)' },
              ]),
            },
          },
        ],
      },
      true,
    )
  }
}

function onResize() {
  donutChart?.resize()
  barChart?.resize()
  trendChart?.resize()
}

onMounted(async () => {
  await loadAll()
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  donutChart?.dispose()
  barChart?.dispose()
  trendChart?.dispose()
})
</script>

<style scoped>
.dashboard-page {
  max-width: 1280px;
  margin: 0 auto;
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--cg-text);
}

.page-sub {
  font-size: 13px;
  color: var(--cg-text-muted);
  margin-top: 4px;
}

/* 统计卡片 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
}

.stat-icon {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--cg-text);
  line-height: 1.2;
}

.stat-label {
  font-size: 12px;
  color: var(--cg-text-muted);
  margin-top: 2px;
}

/* 图表 */
.chart-grid {
  display: grid;
  grid-template-columns: 5fr 7fr;
  gap: 16px;
  margin-bottom: 16px;
}

.bottom-grid {
  display: grid;
  grid-template-columns: 7fr 5fr;
  gap: 16px;
}

.chart-card {
  padding: 18px 20px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--cg-text);
  margin-bottom: 8px;
}

.card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.chart {
  width: 100%;
}

.donut {
  height: 240px;
}

.bar {
  height: 240px;
}

.trend {
  height: 250px;
}

/* 到期列表 */
.empty-tip {
  color: var(--cg-text-muted);
  font-size: 13px;
  text-align: center;
  padding: 48px 0;
}

.due-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 4px;
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: background 0.2s;
}

.due-item:last-child {
  border-bottom: none;
}

.due-item:hover {
  background: #f8fafc;
}

.due-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #94a3b8;
}

.due-dot.expiry {
  background: #ef4444;
}

.due-dot.effective {
  background: #3b82f6;
}

.due-dot.signing {
  background: #94a3b8;
}

.due-dot.payment {
  background: #f59e0b;
}

.due-dot.delivery {
  background: #10b981;
}

.due-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.due-filename {
  font-size: 13px;
  font-weight: 500;
  color: var(--cg-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.due-raw {
  font-size: 12px;
  color: var(--cg-text-muted);
  margin-top: 2px;
}

.due-days {
  font-size: 13px;
  font-weight: 600;
  color: var(--cg-text-secondary);
  flex-shrink: 0;
}

.due-days.urgent {
  color: var(--cg-danger);
}

@media (max-width: 1100px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .chart-grid,
  .bottom-grid {
    grid-template-columns: 1fr;
  }
}
</style>
