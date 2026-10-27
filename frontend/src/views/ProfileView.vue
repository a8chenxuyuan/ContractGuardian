<template>
  <div class="profile-page">
    <div class="page-header">
      <h2>个人中心</h2>
      <p>管理个人资料、账号安全与使用统计</p>
    </div>

    <el-row :gutter="20">
      <!-- 左列：统计卡片 + 最近审查 -->
      <el-col :xs="24" :md="10">
        <div class="stats-grid">
          <div class="stat-card cg-card">
            <div class="stat-icon grad-indigo"><el-icon :size="22"><files /></el-icon></div>
            <div class="stat-info">
              <span class="stat-value">{{ stats?.contract_count ?? '-' }}</span>
              <span class="stat-label">我的合同</span>
            </div>
          </div>
          <div class="stat-card cg-card">
            <div class="stat-icon grad-violet"><el-icon :size="22"><document-checked /></el-icon></div>
            <div class="stat-info">
              <span class="stat-value">{{ stats?.review_count ?? '-' }}</span>
              <span class="stat-label">审查次数</span>
            </div>
          </div>
          <div class="stat-card cg-card">
            <div class="stat-icon grad-rose"><el-icon :size="22"><warning /></el-icon></div>
            <div class="stat-info">
              <span class="stat-value">{{ stats?.risk_levels?.high ?? '-' }}</span>
              <span class="stat-label">高风险发现</span>
            </div>
          </div>
          <div
            class="stat-card cg-card"
            :class="{ clickable: !user?.is_member }"
            @click="!user?.is_member && router.push('/membership')"
          >
            <div class="stat-icon grad-amber"><el-icon :size="22"><medal /></el-icon></div>
            <div class="stat-info">
              <span class="stat-value">{{ memberText }}</span>
              <span class="stat-label">{{ user?.is_member ? '账户类型' : '免费版 · 点击升级' }}</span>
            </div>
          </div>
        </div>

        <div class="cg-card recent-card">
          <h4 class="card-title">最近审查</h4>
          <el-empty v-if="!stats?.recent_reviews?.length" description="还没有审查记录" :image-size="70" />
          <div
            v-for="item in stats?.recent_reviews || []"
            :key="item.id"
            class="recent-item"
            @click="router.push(`/report/${item.contract_id}/${item.id}`)"
          >
            <span class="recent-name">{{ item.filename }}</span>
            <el-tag size="small" :type="statusTagType(item.status)">{{ statusText(item.status) }}</el-tag>
          </div>
        </div>
      </el-col>

      <!-- 右列：资料与安全 -->
      <el-col :xs="24" :md="14">
        <div class="cg-card form-card">
          <h4 class="card-title">基本资料</h4>
          <el-form :model="profileForm" label-width="80px" class="profile-form">
            <el-form-item label="邮箱">
              <el-input :model-value="user?.email" disabled />
            </el-form-item>
            <el-form-item label="昵称">
              <el-input v-model="profileForm.nickname" placeholder="设置一个显示昵称" maxlength="20" />
            </el-form-item>
            <el-form-item label="角色">
              <el-tag v-if="user?.is_admin" type="danger">管理员</el-tag>
              <el-tag v-else-if="user?.is_member" type="warning">会员用户</el-tag>
              <el-tag v-else type="info">免费版</el-tag>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" round @click="saveProfile">保存资料</el-button>
            </el-form-item>
          </el-form>
        </div>

        <div class="cg-card form-card">
          <h4 class="card-title">账号安全</h4>
          <el-form :model="pwdForm" label-width="80px" class="profile-form">
            <el-form-item label="原密码">
              <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="输入当前密码" />
            </el-form-item>
            <el-form-item label="新密码">
              <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位" />
            </el-form-item>
            <el-form-item label="确认密码">
              <el-input v-model="pwdForm.confirm" type="password" show-password placeholder="再次输入新密码" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" round @click="savePassword">修改密码</el-button>
            </el-form-item>
          </el-form>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { changePassword, getMyStats, updateProfile } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import type { MyStats } from '@/types'
import { Files, DocumentChecked, Warning, Medal } from '@element-plus/icons-vue'

const router = useRouter()
const authStore = useAuthStore()

const user = computed(() => authStore.user)
const stats = ref<MyStats | null>(null)

const profileForm = reactive({ nickname: '' })
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

const memberText = computed(() => {
  if (user.value?.is_admin) return '管理员'
  return user.value?.is_member ? '会员用户' : '免费版'
})

function statusText(status: string) {
  const map: Record<string, string> = {
    completed: '已完成',
    running: '审查中',
    pending: '排队中',
    failed: '失败',
  }
  return map[status] || status
}

function statusTagType(status: string) {
  const map: Record<string, 'success' | 'warning' | 'info' | 'danger'> = {
    completed: 'success',
    running: 'warning',
    pending: 'info',
    failed: 'danger',
  }
  return map[status] || 'info'
}

async function loadStats() {
  stats.value = await getMyStats()
}

async function saveProfile() {
  const updated = await updateProfile({ nickname: profileForm.nickname })
  authStore.setUser(updated)
  ElMessage.success('资料已更新')
}

async function savePassword() {
  if (!pwdForm.old_password || !pwdForm.new_password) {
    ElMessage.warning('请填写完整')
    return
  }
  if (pwdForm.new_password.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  await changePassword({ old_password: pwdForm.old_password, new_password: pwdForm.new_password })
  pwdForm.old_password = ''
  pwdForm.new_password = ''
  pwdForm.confirm = ''
}

onMounted(async () => {
  profileForm.nickname = user.value?.nickname || ''
  await loadStats()
})
</script>

<style scoped>
.profile-page {
  max-width: 1080px;
  margin: 0 auto;
}

.page-header h2 {
  font-size: 20px;
  margin: 0 0 4px;
}

.page-header p {
  font-size: 13px;
  color: var(--cg-text-muted);
  margin: 0 0 20px;
}

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
}

.stat-card.clickable {
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.stat-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.14);
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.grad-indigo {
  background: linear-gradient(135deg, #4f46e5, #6366f1);
}

.grad-violet {
  background: linear-gradient(135deg, #7c3aed, #8b5cf6);
}

.grad-rose {
  background: linear-gradient(135deg, #f43f5e, #fb7185);
}

.grad-amber {
  background: linear-gradient(135deg, #f59e0b, #fbbf24);
}

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--cg-text);
}

.stat-label {
  font-size: 12px;
  color: var(--cg-text-muted);
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 14px;
}

.recent-card {
  padding: 18px;
}

.recent-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 13px;
}

.recent-item:last-child {
  border-bottom: none;
}

.recent-name {
  color: var(--cg-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.form-card {
  padding: 20px;
  margin-bottom: 20px;
}

.profile-form {
  max-width: 420px;
}
</style>
