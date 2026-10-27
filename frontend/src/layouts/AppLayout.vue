<template>
  <el-container class="app-layout">
    <!-- 侧边栏 -->
    <el-aside :width="collapsed ? '64px' : '220px'" class="sidebar">
      <div class="brand-area" @click="router.push('/')">
        <div class="brand-logo">
          <el-icon :size="22"><lock /></el-icon>
        </div>
        <transition name="fade-text">
          <div v-if="!collapsed" class="brand-text">
            <span class="brand-name">合同卫士</span>
            <span class="brand-sub">AI 合同审查平台</span>
          </div>
        </transition>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="collapsed"
        :collapse-transition="false"
        router
        class="sidebar-menu"
      >
        <el-menu-item index="/contracts">
          <el-icon><files /></el-icon>
          <template #title>合同工作台</template>
        </el-menu-item>
        <el-menu-item index="/upload">
          <el-icon><upload-filled /></el-icon>
          <template #title>上传合同</template>
        </el-menu-item>
        <el-menu-item index="/dashboard">
          <el-icon><data-analysis /></el-icon>
          <template #title>风险看板</template>
        </el-menu-item>
        <el-menu-item index="/calendar">
          <el-icon><calendar /></el-icon>
          <template #title>履约日历</template>
        </el-menu-item>
        <el-menu-item index="/notifications">
          <el-icon><bell /></el-icon>
          <template #title>通知中心</template>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><reading /></el-icon>
          <template #title>法规知识库</template>
        </el-menu-item>
        <el-menu-item index="/templates">
          <el-icon><document /></el-icon>
          <template #title>合同模板库</template>
        </el-menu-item>
        <el-menu-item index="/membership">
          <el-icon><service /></el-icon>
          <template #title>会员中心</template>
        </el-menu-item>
        <el-menu-item index="/profile">
          <el-icon><user /></el-icon>
          <template #title>个人中心</template>
        </el-menu-item>
        <el-menu-item v-if="user?.is_admin" index="/admin">
          <el-icon><setting /></el-icon>
          <template #title>管理后台</template>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <div v-if="!collapsed" class="pro-card">
          <el-icon :size="20"><magic-stick /></el-icon>
          <p class="pro-title">14 Agent 智能协作</p>
          <p class="pro-desc">多维度交叉验证风险</p>
        </div>
        <div class="user-row" @click="collapsed = !collapsed">
          <el-avatar :size="32" class="user-avatar">
            {{ avatarText }}
          </el-avatar>
          <div v-if="!collapsed" class="user-meta">
            <span class="user-name">{{ user?.nickname || user?.email || '用户' }}</span>
            <span class="user-role">{{ user?.is_member ? '会员用户' : '免费版' }}</span>
          </div>
          <el-tooltip content="折叠/展开" placement="right" v-if="collapsed">
            <el-icon class="collapse-arrow"><d-arrow-right /></el-icon>
          </el-tooltip>
        </div>
      </div>
    </el-aside>

    <!-- 主区域 -->
    <el-container class="main-area">
      <el-header class="topbar">
        <div class="topbar-left">
          <el-icon class="collapse-btn" @click="collapsed = !collapsed">
            <expand v-if="collapsed" />
            <fold v-else />
          </el-icon>
          <span class="topbar-title">{{ pageTitle }}</span>
        </div>
        <div class="topbar-actions">
          <el-button type="primary" round @click="router.push('/upload')">
            <el-icon style="margin-right: 4px"><plus /></el-icon>
            上传合同
          </el-button>

          <!-- 通知中心 -->
          <el-badge :value="unreadCount" :hidden="!unreadCount" :max="99" class="bell-badge">
            <el-popover placement="bottom-end" :width="360" trigger="click" @show="loadNotifications">
              <template #reference>
                <el-icon class="bell-btn"><bell /></el-icon>
              </template>
              <div class="notif-panel">
                <div class="notif-head">
                  <span>通知中心</span>
                  <div>
                    <el-button link type="primary" size="small" @click="router.push('/notifications')">
                      查看全部
                    </el-button>
                    <el-button v-if="notifications.length" link type="primary" size="small" @click="onReadAll">
                      全部已读
                    </el-button>
                  </div>
                </div>
                <div v-if="!notifications.length" class="notif-empty">暂无通知</div>
                <div
                  v-for="item in notifications"
                  :key="item.id"
                  class="notif-item"
                  :class="{ unread: !item.is_read }"
                  @click="onNotificationClick(item)"
                >
                  <div class="notif-title">
                    <span class="notif-dot" v-if="!item.is_read" />
                    {{ item.title }}
                  </div>
                  <div class="notif-content">{{ item.content }}</div>
                  <div class="notif-time">{{ formatTime(item.created_at) }}</div>
                </div>
              </div>
            </el-popover>
          </el-badge>

          <el-dropdown trigger="click" @command="onUserCommand">
            <el-avatar :size="34" class="topbar-avatar">{{ avatarText }}</el-avatar>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  {{ user?.email }}
                </el-dropdown-item>
                <el-dropdown-item v-if="user?.is_admin" command="admin">
                  <el-icon><setting /></el-icon>管理后台
                </el-dropdown-item>
                <el-dropdown-item divided command="logout">
                  <el-icon><switch-button /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="page-main">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { listNotifications, readNotification, readAllNotifications, getUnreadCount } from '@/api/admin'
import type { AppNotification } from '@/types'
import {
  Lock, Files, UploadFilled, Setting, MagicStick, Expand, Fold, Plus,
  SwitchButton, DArrowRight, Bell, User, Service, DataAnalysis, Calendar, Reading, Document,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const collapsed = ref(false)
const user = computed(() => authStore.user)
const avatarText = computed(() => {
  const name = user.value?.nickname || user.value?.email || '用'
  return name.slice(0, 1).toUpperCase()
})

// ---------- 通知中心 ----------
const notifications = ref<AppNotification[]>([])
const unreadCount = ref(0)
let pollTimer: number | null = null

async function loadUnread() {
  try {
    const res = await getUnreadCount()
    unreadCount.value = res.unread_count
  } catch {
    // 轮询失败静默处理
  }
}

async function loadNotifications() {
  try {
    const res = await listNotifications()
    notifications.value = res.items
    unreadCount.value = res.unread_count
  } catch {
    // 打开面板失败静默处理
  }
}

async function onReadAll() {
  await readAllNotifications()
  await loadNotifications()
}

async function onNotificationClick(item: AppNotification) {
  if (!item.is_read) {
    await readNotification(item.id)
    unreadCount.value = Math.max(0, unreadCount.value - 1)
    item.is_read = true
  }
  if (item.contract_id && item.related_id) {
    router.push(`/report/${item.contract_id}/${item.related_id}`)
  }
}

function formatTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  loadUnread()
  pollTimer = window.setInterval(loadUnread, 30000)
  // 通知中心页标记已读后立即同步红点，不等 30s 轮询
  window.addEventListener('cg:unread-changed', loadUnread)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  window.removeEventListener('cg:unread-changed', loadUnread)
})

// ---------- 菜单 ----------
const activeMenu = computed(() => {
  if (route.path.startsWith('/upload')) return '/upload'
  if (route.path.startsWith('/dashboard')) return '/dashboard'
  if (route.path.startsWith('/calendar')) return '/calendar'
  if (route.path.startsWith('/notifications')) return '/notifications'
  if (route.path.startsWith('/knowledge')) return '/knowledge'
  if (route.path.startsWith('/templates')) return '/templates'
  if (route.path.startsWith('/admin')) return '/admin'
  if (route.path.startsWith('/profile')) return '/profile'
  if (route.path.startsWith('/membership')) return '/membership'
  return '/contracts'
})

const pageTitle = computed(() => {
  const map: Record<string, string> = {
    Contracts: '合同工作台',
    Upload: '上传合同',
    Dashboard: '风险台账看板',
    Calendar: '履约日历',
    Notifications: '通知中心',
    Admin: '管理后台',
    Profile: '个人中心',
    Membership: '会员中心',
  }
  return map[(route.name as string) || ''] || '合同卫士'
})

function onUserCommand(cmd: string) {
  if (cmd === 'logout') {
    authStore.logout()
    router.push('/login')
  } else if (cmd === 'admin') {
    router.push('/admin')
  }
}
</script>

<style scoped>
.app-layout {
  height: 100%;
}

/* ---------- 侧边栏 ---------- */
.sidebar {
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-right: 1px solid var(--cg-border);
  transition: width 0.25s ease;
  overflow: hidden;
}

.brand-area {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px;
  cursor: pointer;
  min-height: 68px;
}

.brand-logo {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: var(--cg-gradient);
  color: #fff;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.35);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  white-space: nowrap;
}

.brand-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--cg-text);
}

.brand-sub {
  font-size: 11px;
  color: var(--cg-text-muted);
}

.sidebar-menu {
  border-right: none;
  flex: 1;
  padding: 4px 8px;
}

.sidebar-menu :deep(.el-menu-item) {
  border-radius: 8px;
  margin-bottom: 4px;
  height: 44px;
  color: var(--cg-text-secondary);
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  background: var(--cg-gradient-soft);
  color: var(--cg-primary);
  font-weight: 600;
}

.sidebar-menu :deep(.el-menu-item:hover) {
  background: #f8fafc;
}

/* 侧边栏底部 */
.sidebar-footer {
  padding: 12px;
}

.pro-card {
  background: var(--cg-gradient);
  border-radius: 12px;
  padding: 14px;
  color: #fff;
  margin-bottom: 12px;
  white-space: nowrap;
  overflow: hidden;
}

.pro-title {
  font-size: 13px;
  font-weight: 600;
  margin-top: 6px;
}

.pro-desc {
  font-size: 11px;
  opacity: 0.85;
  margin-top: 2px;
}

.user-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s;
}

.user-row:hover {
  background: #f1f5f9;
}

.user-avatar {
  background: var(--cg-gradient);
  color: #fff;
  font-weight: 600;
  flex-shrink: 0;
}

.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--cg-text);
}

.user-role {
  font-size: 11px;
  color: var(--cg-text-muted);
}

.collapse-arrow {
  margin-left: auto;
  color: var(--cg-text-muted);
}

/* ---------- 顶栏 ---------- */
.main-area {
  min-width: 0;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--cg-border);
  padding: 0 24px;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.collapse-btn {
  font-size: 18px;
  color: var(--cg-text-secondary);
  cursor: pointer;
}

.topbar-title {
  font-size: 15px;
  font-weight: 600;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.topbar-avatar {
  background: var(--cg-gradient);
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}

/* ---------- 通知中心 ---------- */
.bell-badge {
  display: flex;
  align-items: center;
}

.bell-btn {
  font-size: 19px;
  color: var(--cg-text-secondary);
  cursor: pointer;
  transition: color 0.2s;
}

.bell-btn:hover {
  color: var(--cg-primary);
}

.notif-panel {
  max-height: 380px;
  overflow-y: auto;
}

.notif-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--cg-border);
}

.notif-empty {
  text-align: center;
  color: var(--cg-text-muted);
  font-size: 13px;
  padding: 32px 0;
}

.notif-item {
  padding: 10px 4px;
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: background 0.2s;
}

.notif-item:hover {
  background: #f8fafc;
}

.notif-item.unread .notif-title {
  font-weight: 600;
}

.notif-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--cg-text);
}

.notif-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--cg-primary);
  flex-shrink: 0;
}

.notif-content {
  font-size: 12px;
  color: var(--cg-text-secondary);
  margin-top: 4px;
  line-height: 1.5;
}

.notif-time {
  font-size: 11px;
  color: var(--cg-text-muted);
  margin-top: 4px;
}

/* ---------- 主内容 ---------- */
.page-main {
  background: var(--cg-bg);
  padding: 24px;
  overflow-y: auto;
}

/* 文字淡入 */
.fade-text-enter-active {
  transition: opacity 0.2s ease;
}
.fade-text-leave-active {
  display: none;
}
.fade-text-enter-from {
  opacity: 0;
}
</style>
