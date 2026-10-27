<template>
  <div class="notif-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">通知中心</h2>
        <p class="page-sub">审查完成、履约提醒等消息都在这里</p>
      </div>
      <el-button :disabled="!unreadCount" round @click="onReadAll">
        <el-icon style="margin-right: 4px"><check /></el-icon>
        全部已读
      </el-button>
    </div>

    <div class="cg-card list-card">
      <el-tabs v-model="activeTab" class="notif-tabs" @tab-change="onTabChange">
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane name="unread">
          <template #label>
            未读
            <el-badge v-if="unreadCount" :value="unreadCount" :max="99" class="tab-badge" />
          </template>
        </el-tab-pane>
        <el-tab-pane label="已读" name="read" />
      </el-tabs>

      <div v-if="loading" class="empty-tip">加载中…</div>
      <div v-else-if="!items.length" class="empty-tip">暂无通知</div>
      <div
        v-for="item in items"
        :key="item.id"
        class="notif-row"
        :class="{ unread: !item.is_read }"
        @click="onClick(item)"
      >
        <span class="type-dot" :class="item.type" />
        <div class="notif-main">
          <div class="notif-title">
            {{ item.title }}
            <el-tag v-if="item.type === 'key_date'" size="small" type="warning" effect="plain" round>
              履约提醒
            </el-tag>
          </div>
          <div v-if="item.content" class="notif-content">{{ item.content }}</div>
          <div class="notif-time">{{ formatTime(item.created_at) }}</div>
        </div>
        <el-button
          v-if="!item.is_read"
          link
          type="primary"
          size="small"
          @click.stop="onMarkRead(item)"
        >
          标为已读
        </el-button>
      </div>

      <div v-if="total > pageSize" class="pager">
        <el-pagination
          layout="prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check } from '@element-plus/icons-vue'
import { listNotifications, readNotification, readAllNotifications } from '@/api/admin'
import type { AppNotification } from '@/types'

const router = useRouter()
const items = ref<AppNotification[]>([])
const total = ref(0)
const unreadCount = ref(0)
const activeTab = ref<'all' | 'unread' | 'read'>('all')
const page = ref(1)
const pageSize = 20
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await listNotifications({
      skip: (page.value - 1) * pageSize,
      limit: pageSize,
      is_read: activeTab.value === 'all' ? undefined : activeTab.value === 'read',
    })
    items.value = res.items
    total.value = res.total
    unreadCount.value = res.unread_count
  } finally {
    loading.value = false
  }
}

function onTabChange() {
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function notifyLayoutRefresh() {
  window.dispatchEvent(new CustomEvent('cg:unread-changed'))
}

async function onMarkRead(item: AppNotification) {
  await readNotification(item.id)
  item.is_read = true
  unreadCount.value = Math.max(0, unreadCount.value - 1)
  notifyLayoutRefresh()
}

async function onReadAll() {
  await readAllNotifications()
  ElMessage.success('已全部标记为已读')
  page.value = 1
  await load()
  notifyLayoutRefresh()
}

function onClick(item: AppNotification) {
  if (!item.is_read) onMarkRead(item)
  if (item.type === 'key_date' && item.contract_id) {
    router.push('/contracts')
  } else if (item.contract_id && item.related_id) {
    router.push(`/report/${item.contract_id}/${item.related_id}`)
  }
}

function formatTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<style scoped>
.notif-page {
  max-width: 880px;
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

.list-card {
  padding: 8px 20px 16px;
}

.tab-badge {
  margin-left: 6px;
  vertical-align: 2px;
}

.notif-tabs :deep(.el-tabs__header) {
  margin-bottom: 4px;
}

.empty-tip {
  color: var(--cg-text-muted);
  font-size: 13px;
  text-align: center;
  padding: 56px 0;
}

.notif-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 4px;
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: background 0.2s;
}

.notif-row:last-of-type {
  border-bottom: none;
}

.notif-row:hover {
  background: #f8fafc;
}

.type-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 7px;
  flex-shrink: 0;
  background: var(--cg-border);
}

.notif-row.unread .type-dot {
  background: var(--cg-primary);
}

.notif-row.unread .notif-title {
  font-weight: 600;
}

.notif-main {
  flex: 1;
  min-width: 0;
}

.notif-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--cg-text);
}

.notif-content {
  font-size: 13px;
  color: var(--cg-text-secondary);
  margin-top: 4px;
  line-height: 1.6;
}

.notif-time {
  font-size: 12px;
  color: var(--cg-text-muted);
  margin-top: 4px;
}

.pager {
  display: flex;
  justify-content: center;
  padding-top: 14px;
}
</style>
