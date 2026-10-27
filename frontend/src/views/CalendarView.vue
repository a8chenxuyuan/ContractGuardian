<template>
  <div class="calendar-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">履约日历</h2>
        <p class="page-sub">合同关键日期一目了然，点击事项可跳转对应报告</p>
      </div>
      <div class="month-nav">
        <el-button circle :icon="ArrowLeft" @click="shiftMonth(-1)" />
        <span class="month-title">{{ year }} 年 {{ month }} 月</span>
        <el-button circle :icon="ArrowRight" @click="shiftMonth(1)" />
        <el-button round size="small" @click="goToday">今天</el-button>
      </div>
    </div>

    <div class="cg-card grid-card">
      <div class="legend">
        <span v-for="(t, key) in TYPE_META" :key="key" class="legend-item">
          <span class="legend-dot" :style="{ background: t.color }" />{{ t.label }}
        </span>
      </div>
      <div class="grid-head">
        <span v-for="w in WEEKS" :key="w" class="week-label">{{ w }}</span>
      </div>
      <div class="grid-body">
        <div
          v-for="(cell, idx) in cells"
          :key="idx"
          class="day-cell"
          :class="{ blank: !cell.day, today: cell.dateStr === today }"
        >
          <template v-if="cell.day">
            <span class="day-num">{{ cell.day }}</span>
            <div class="event-list">
              <div
                v-for="ev in eventsByDate[cell.dateStr] || []"
                :key="ev.id"
                class="event-chip"
                :style="{ background: (TYPE_META[ev.date_type] || TYPE_META.other).bg, color: (TYPE_META[ev.date_type] || TYPE_META.other).color }"
                :title="`${ev.filename} · ${ev.raw_text}`"
                @click="goReport(ev)"
              >
                {{ (TYPE_META[ev.date_type] || TYPE_META.other).label }}
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <div class="cg-card list-card">
      <h3 class="card-title">本月事项（{{ monthItems.length }}）</h3>
      <div v-if="!monthItems.length" class="empty-tip">本月暂无履约事项</div>
      <div
        v-for="item in monthItems"
        :key="item.id"
        class="event-row"
        @click="goReport(item)"
      >
        <span class="event-date">{{ formatDate(item.date_value) }}</span>
        <span class="event-tag" :style="{ background: (TYPE_META[item.date_type] || TYPE_META.other).bg, color: (TYPE_META[item.date_type] || TYPE_META.other).color }">
          {{ (TYPE_META[item.date_type] || TYPE_META.other).label }}
        </span>
        <span class="event-filename">{{ item.filename }}</span>
        <span class="event-raw">{{ item.raw_text }}</span>
        <span class="event-days" :class="{ urgent: item.days_left >= 0 && item.days_left <= 7 }">
          {{ daysLabel(item.days_left) }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { getCalendar, type CalendarItem } from '@/api/dashboard'

const router = useRouter()
const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth() + 1)
const items = ref<CalendarItem[]>([])
const today = ref('')

const WEEKS = ['一', '二', '三', '四', '五', '六', '日']

const TYPE_META: Record<string, { label: string; color: string; bg: string }> = {
  expiry: { label: '到期', color: '#b91c1c', bg: '#fee2e2' },
  effective: { label: '生效', color: '#1d4ed8', bg: '#dbeafe' },
  signing: { label: '签署', color: '#475569', bg: '#e2e8f0' },
  payment: { label: '付款', color: '#b45309', bg: '#fef3c7' },
  delivery: { label: '交付', color: '#047857', bg: '#d1fae5' },
  other: { label: '其他', color: '#475569', bg: '#f1f5f9' },
}

interface Cell {
  day: number | null
  dateStr: string
}

const cells = computed<Cell[]>(() => {
  const first = new Date(year.value, month.value - 1, 1)
  const lastDay = new Date(year.value, month.value, 0).getDate()
  const offset = (first.getDay() + 6) % 7 // 周一开头
  const list: Cell[] = []
  for (let i = 0; i < offset; i++) {
    list.push({ day: null, dateStr: '' })
  }
  for (let d = 1; d <= lastDay; d++) {
    list.push({ day: d, dateStr: fmtDate(year.value, month.value, d) })
  }
  return list
})

const eventsByDate = computed<Record<string, CalendarItem[]>>(() => {
  const map: Record<string, CalendarItem[]> = {}
  for (const it of items.value) {
    ;(map[it.date_value] ||= []).push(it)
  }
  return map
})

const monthItems = computed(() => items.value)

function fmtDate(y: number, m: number, d: number) {
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

async function load() {
  const res = await getCalendar(year.value, month.value)
  items.value = res.items
  today.value = res.today
}

function shiftMonth(delta: number) {
  let m = month.value + delta
  let y = year.value
  if (m < 1) {
    m = 12
    y -= 1
  } else if (m > 12) {
    m = 1
    y += 1
  }
  year.value = y
  month.value = m
}

function goToday() {
  const now2 = new Date()
  year.value = now2.getFullYear()
  month.value = now2.getMonth() + 1
}

function goReport(item: CalendarItem) {
  if (item.contract_id && item.review_session_id) {
    router.push(`/report/${item.contract_id}/${item.review_session_id}`)
  } else {
    ElMessage.info('该事项暂无对应审查报告')
  }
}

function formatDate(value: string) {
  return value.slice(5).replace('-', '/')
}

function daysLabel(days: number) {
  if (days < 0) return '已过期'
  if (days === 0) return '今天'
  return `${days} 天`
}

watch([year, month], load)
onMounted(load)
</script>

<style scoped>
.calendar-page {
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

.month-nav {
  display: flex;
  align-items: center;
  gap: 12px;
}

.month-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--cg-text);
  min-width: 110px;
  text-align: center;
}

.grid-card {
  padding: 16px 20px;
  margin-bottom: 16px;
}

.legend {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--cg-text-secondary);
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.grid-head,
.grid-body {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
}

.week-label {
  text-align: center;
  font-size: 12px;
  color: var(--cg-text-muted);
  padding: 6px 0 10px;
}

.day-cell {
  min-height: 96px;
  border-top: 1px solid #f1f5f9;
  border-left: 1px solid #f1f5f9;
  padding: 6px;
  overflow: hidden;
}

.day-cell:nth-child(7n + 1) {
  border-left: none;
}

.day-cell.today {
  background: var(--cg-gradient-soft);
  border-radius: 6px;
}

.day-num {
  font-size: 13px;
  font-weight: 500;
  color: var(--cg-text-secondary);
}

.today .day-num {
  color: var(--cg-primary);
  font-weight: 700;
}

.event-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 4px;
}

.event-chip {
  font-size: 11px;
  line-height: 1;
  padding: 4px 6px;
  border-radius: 5px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: transform 0.15s;
}

.event-chip:hover {
  transform: translateY(-1px);
}

/* 本月事项列表 */
.list-card {
  padding: 16px 20px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--cg-text);
  margin-bottom: 6px;
}

.empty-tip {
  color: var(--cg-text-muted);
  font-size: 13px;
  text-align: center;
  padding: 32px 0;
}

.event-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 4px;
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: background 0.2s;
}

.event-row:last-child {
  border-bottom: none;
}

.event-row:hover {
  background: #f8fafc;
}

.event-date {
  font-size: 13px;
  font-weight: 600;
  color: var(--cg-text);
  width: 48px;
  flex-shrink: 0;
}

.event-tag {
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 5px;
  flex-shrink: 0;
}

.event-filename {
  font-size: 13px;
  color: var(--cg-text);
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.event-raw {
  font-size: 12px;
  color: var(--cg-text-muted);
  flex-shrink: 0;
}

.event-days {
  font-size: 12px;
  color: var(--cg-text-secondary);
  width: 52px;
  text-align: right;
  flex-shrink: 0;
}

.event-days.urgent {
  color: var(--cg-danger);
  font-weight: 600;
}
</style>
