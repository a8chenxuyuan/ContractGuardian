<template>
  <div class="dashboard">
    <!-- 欢迎横幅 -->
    <div class="welcome-banner">
      <div class="welcome-text">
        <h2>{{ greeting }}，{{ userName }}</h2>
        <p>上传合同，AI 将从 {{ agentCount }} 个专业维度为你审查风险</p>
      </div>
      <el-button type="primary" size="large" round class="banner-btn" @click="router.push('/upload')">
        <el-icon style="margin-right: 6px"><plus /></el-icon>
        立即上传合同
      </el-button>
      <div class="banner-deco"></div>
    </div>

    <!-- KPI 统计卡 -->
    <div class="kpi-grid" v-if="!loading && viewMode === 'list'">
      <div class="kpi-card" v-for="k in kpis" :key="k.label" :style="{ '--kpi-color': k.color }">
        <div class="kpi-icon">
          <el-icon :size="20"><component :is="k.icon" /></el-icon>
        </div>
        <div class="kpi-meta">
          <span class="kpi-value">{{ k.value }}</span>
          <span class="kpi-label">{{ k.label }}</span>
        </div>
      </div>
    </div>

    <!-- 搜索筛选工具栏 -->
    <div class="filter-bar cg-card" v-if="viewMode === 'list'">
      <el-input
        v-model="filters.keyword"
        placeholder="搜索合同文件名..."
        clearable
        class="filter-search"
        :prefix-icon="Search"
        @keyup.enter="loadContracts"
        @clear="loadContracts"
      />
      <el-select v-model="filters.status" placeholder="状态" clearable class="filter-select" @change="loadContracts">
        <el-option label="待审查" value="parsed" />
        <el-option label="审查中" value="reviewing" />
        <el-option label="已完成" value="completed" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-select v-model="filters.risk" placeholder="风险等级" clearable class="filter-select" @change="loadContracts">
        <el-option label="含高风险" value="high" />
        <el-option label="含中风险" value="medium" />
        <el-option label="含低风险" value="low" />
        <el-option label="无风险" value="clean" />
      </el-select>
      <el-select v-model="filters.sort" class="filter-select" @change="loadContracts">
        <el-option label="最新上传" value="newest" />
        <el-option label="最早上传" value="oldest" />
        <el-option label="文件名 A-Z" value="name" />
      </el-select>
      <div class="filter-spacer" />
      <el-button round @click="toggleTrash">
        <el-icon style="margin-right: 4px"><delete /></el-icon>
        回收站{{ trashCount ? ` (${trashCount})` : '' }}
      </el-button>
    </div>

    <!-- 回收站模式提示 -->
    <div class="trash-banner" v-if="viewMode === 'trash'">
      <el-alert type="warning" :closable="false" show-icon>
        <template #title>
          回收站中的合同将在删除 30 天后自动清理，恢复后将回到合同工作台。
        </template>
      </el-alert>
      <el-button round @click="toggleTrash">
        <el-icon style="margin-right: 4px"><back /></el-icon>返回列表
      </el-button>
    </div>

    <!-- 合同列表 -->
    <div class="section-header" v-if="viewMode === 'list'">
      <h3>我的合同</h3>
      <el-button text type="primary" @click="router.push('/upload')">
        <el-icon><plus /></el-icon> 上传新合同
      </el-button>
    </div>
    <div class="section-header" v-else>
      <h3>回收站</h3>
    </div>

    <el-skeleton :rows="4" animated v-if="loading" />

    <div v-else-if="contracts.length === 0" class="empty-state cg-card">
      <div class="empty-icon">
        <el-icon :size="44"><folder-add /></el-icon>
      </div>
      <h4>{{ viewMode === 'trash' ? '回收站是空的' : '还没有合同' }}</h4>
      <p>{{ viewMode === 'trash' ? '删除的合同会先进入回收站' : '上传你的第一份合同，体验 AI 多 Agent 智能审查' }}</p>
      <el-button v-if="viewMode === 'list'" type="primary" round @click="router.push('/upload')">上传合同</el-button>
    </div>

    <div v-else class="contract-grid">
      <div
        v-for="c in contracts"
        :key="c.id"
        class="contract-card cg-card"
        :class="{ 'is-danger': highRisk(c) > 0 }"
      >
        <div class="card-top">
          <div class="file-badge" :class="'type-' + fileType(c)">
            <el-icon :size="20"><document /></el-icon>
            <span>{{ fileType(c).toUpperCase() }}</span>
          </div>
          <el-tag :type="statusType(c.status)" size="small" effect="light" round>
            {{ statusText(c.status) }}
          </el-tag>
        </div>

        <h4 class="card-filename" :title="c.filename">{{ c.filename }}</h4>
        <p class="card-date">
          <el-icon><clock /></el-icon>
          {{ formatDate(c.created_at) }}
          <span v-if="c.page_count"> · {{ c.page_count }} 页</span>
        </p>

        <!-- 风险摘要 -->
        <div class="risk-strip" v-if="c.risk_summary && hasRisk(c.risk_summary)">
          <span class="risk-chip high" v-if="c.risk_summary.high">
            高风险 {{ c.risk_summary.high }}
          </span>
          <span class="risk-chip medium" v-if="c.risk_summary.medium">
            中风险 {{ c.risk_summary.medium }}
          </span>
          <span class="risk-chip low" v-if="c.risk_summary.low">
            低风险 {{ c.risk_summary.low }}
          </span>
        </div>
        <div class="risk-strip" v-else>
          <span class="risk-chip none">
            {{ c.status === 'completed' ? '未发现风险' : '暂无审查结果' }}
          </span>
        </div>

        <!-- 到期倒计时（履约日期管家） -->
        <div class="expiry-strip" v-if="c.nearest_expiry && expiryDays(c.nearest_expiry) <= 30">
          <el-icon :size="13"><alarm-clock /></el-icon>
          <span :class="{ urgent: expiryDays(c.nearest_expiry) <= 7 }">
            {{ expiryText(c.nearest_expiry) }}
          </span>
        </div>

        <div class="card-actions" v-if="viewMode === 'list'">
          <el-button
            v-if="c.status === 'parsed' || c.status === 'completed'"
            type="primary"
            size="small"
            round
            :loading="reviewLoading === c.id"
            @click="handleStartReview(c.id)"
          >
            开始审查
          </el-button>
          <el-button
            v-if="c.status === 'completed' && c.latest_review_session_id"
            type="success"
            size="small"
            plain
            round
            @click="viewReport(c.id, c.latest_review_session_id)"
          >
            查看报告
          </el-button>
          <el-button v-if="canPreview(c)" size="small" plain round @click="openPreview(c)">
            预览
          </el-button>
          <el-dropdown trigger="click" @command="(cmd: string) => onMoreCommand(cmd, c)">
            <el-button size="small" text>
              更多<el-icon class="el-icon--right"><arrow-down /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="versions">
                  <el-icon><folder-opened /></el-icon>版本管理
                </el-dropdown-item>
                <el-dropdown-item v-if="(c.version_count || 1) > 1" command="diff">
                  <el-icon><switch /></el-icon>对比审查
                </el-dropdown-item>
                <el-dropdown-item command="reupload">
                  <el-icon><refresh-right /></el-icon>重新上传
                </el-dropdown-item>
                <el-dropdown-item command="delete" divided>
                  <span style="color: var(--el-color-danger)">
                    <el-icon><delete /></el-icon> 删除
                  </span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <!-- 回收站模式操作 -->
        <div class="card-actions" v-else>
          <el-tag size="small" type="info" effect="plain">
            {{ formatDate(c.deleted_at) }} 删除
          </el-tag>
          <div class="trash-actions">
            <el-button type="primary" size="small" plain round @click="handleRestore(c.id)">
              恢复
            </el-button>
            <el-button type="danger" size="small" text @click="handlePurge(c.id)">
              彻底删除
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 预览弹窗 -->
    <el-dialog
      v-model="previewVisible"
      :title="previewContract?.filename || '合同预览'"
      width="80%"
      top="4vh"
      destroy-on-close
      class="preview-dialog"
      @closed="revokePreview"
    >
      <div class="preview-body" v-loading="previewLoading">
        <iframe
          v-if="previewType === 'pdf' && previewBlobUrl"
          :src="previewBlobUrl"
          class="preview-frame"
        />
        <img
          v-else-if="previewType === 'image' && previewBlobUrl"
          :src="previewBlobUrl"
          class="preview-image"
        />
      </div>
    </el-dialog>

    <!-- 版本管理弹窗 -->
    <el-dialog v-model="versionsVisible" title="版本管理" width="560px">
      <div v-loading="versionsLoading">
        <el-table :data="versions" size="small">
          <el-table-column label="版本" width="80">
            <template #default="{ row }">
              <el-tag v-if="row.is_current" type="success" size="small">当前 v{{ row.version }}</el-tag>
              <span v-else>v{{ row.version }}</span>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
          </el-table-column>
          <el-table-column label="上传时间">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="downloadVersion(row.version)">
                下载
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="versions-tip">
          重新上传会生成新版本并触发重新解析，历史版本可随时下载。
        </div>
      </div>
    </el-dialog>

    <!-- 重新上传弹窗 -->
    <el-dialog v-model="reuploadVisible" title="重新上传合同" width="460px">
      <p class="reupload-tip">
        为《{{ reuploadContract?.filename }}》上传新版本文件，解析完成后旧版本仍可下载。
      </p>
      <el-upload
        drag
        action="#"
        :auto-upload="false"
        :show-file-list="false"
        :on-change="onReuploadFile"
        accept=".pdf,.doc,.docx,.png,.jpg,.jpeg"
      >
        <div class="reupload-drop">
          <el-icon :size="26"><upload-filled /></el-icon>
          <span v-if="reuploadFile">{{ reuploadFile.name }}</span>
          <span v-else class="reupload-hint">点击或拖拽选择新版本文件</span>
        </div>
      </el-upload>
      <template #footer>
        <el-button round @click="reuploadVisible = false">取消</el-button>
        <el-button type="primary" round :loading="reuploading" :disabled="!reuploadFile" @click="handleReupload">
          上传并解析
        </el-button>
      </template>
    </el-dialog>

    <!-- 对比审查弹窗 -->
    <el-dialog v-model="diffVisible" title="双版本对比审查" width="460px">
      <p class="reupload-tip">
        选择《{{ diffContract?.filename }}》的一个历史版本作为基准，系统将对当前版本做条款级对比，
        并在审查报告中标注修改引入的风险。
      </p>
      <el-select v-model="diffBaseVersion" placeholder="选择基准版本" size="large" style="width: 100%">
        <el-option
          v-for="v in diffVersions"
          :key="v.version"
          :label="`v${v.version} · ${formatDate(v.created_at)}`"
          :value="v.version"
          :disabled="v.is_current"
        />
      </el-select>
      <template #footer>
        <el-button round @click="diffVisible = false">取消</el-button>
        <el-button type="primary" round :loading="diffStarting" :disabled="!diffBaseVersion" @click="handleDiffReview">
          启动对比审查
        </el-button>
      </template>
    </el-dialog>

    <PaywallDialog
      v-model="paywallVisible"
      :reason="paywallReason"
      :used="paywallUsed"
      :limit="paywallLimit"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, Document, Clock, FolderAdd, Files, CircleCheck, WarningFilled,
  Odometer, Search, Delete, Back, ArrowDown, FolderOpened, RefreshRight, UploadFilled, Switch, AlarmClock,
} from '@element-plus/icons-vue'
import {
  getContracts, getTrashContracts, deleteContract, restoreContract, purgeContract,
  reuploadContract as reuploadContractApi, getContractVersions, previewContractFile,
  downloadContractFile, type ContractFileVersion,
} from '@/api/contracts'
import { startReview } from '@/api/review'
import PaywallDialog from '@/components/PaywallDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { Contract } from '@/types'

const router = useRouter()
const authStore = useAuthStore()
const contracts = ref<Contract[]>([])
const loading = ref(false)
const reviewLoading = ref<number | null>(null)

// ---------- 列表筛选与回收站 ----------
const viewMode = ref<'list' | 'trash'>('list')
const trashCount = ref(0)
const filters = reactive({ keyword: '', status: '', risk: '', sort: 'newest' })

function toggleTrash() {
  viewMode.value = viewMode.value === 'list' ? 'trash' : 'list'
  loadContracts()
}

const agentCount = 14
const userName = computed(() => authStore.user?.nickname || '朋友')
const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const kpis = computed(() => {
  const total = contracts.value.length
  const completed = contracts.value.filter((c) => c.status === 'completed').length
  let totalRisk = 0
  let highRisk = 0
  for (const c of contracts.value) {
    if (c.risk_summary) {
      totalRisk += (c.risk_summary.high || 0) + (c.risk_summary.medium || 0) + (c.risk_summary.low || 0)
      highRisk += c.risk_summary.high || 0
    }
  }
  return [
    { label: '合同总数', value: total, icon: Files, color: '#4f46e5' },
    { label: '已完成审查', value: completed, icon: CircleCheck, color: '#10b981' },
    { label: '累计风险发现', value: totalRisk, icon: WarningFilled, color: '#f59e0b' },
    { label: '高风险合同', value: highRisk, icon: Odometer, color: '#ef4444' },
  ]
})

function fileType(c: Contract) {
  return (c.file_type || 'file').toLowerCase()
}

function highRisk(c: Contract) {
  return c.risk_summary?.high || 0
}

function hasRisk(s: Record<string, number>) {
  return (s.high || 0) + (s.medium || 0) + (s.low || 0) > 0
}

function statusType(status: string) {
  const map: Record<string, string> = {
    uploaded: 'info',
    parsing: 'warning',
    parsed: 'primary',
    reviewing: 'warning',
    completed: 'success',
    failed: 'danger',
  }
  return (map[status] || 'info') as any
}

function statusText(status: string) {
  const map: Record<string, string> = {
    uploaded: '已上传',
    parsing: '解析中',
    parsed: '待审查',
    reviewing: '审查中',
    completed: '已完成',
    failed: '失败',
  }
  return map[status] || status
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}

// 到期倒计时（履约日期管家）
function expiryDays(dateStr: string) {
  const diff = new Date(`${dateStr}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()
  return Math.round(diff / 86400000)
}

function expiryText(dateStr: string) {
  const n = expiryDays(dateStr)
  if (n < 0) return '已于 ' + new Date(`${dateStr}T00:00:00`).toLocaleDateString('zh-CN') + ' 到期'
  if (n === 0) return '今天到期'
  return `${n} 天后到期（${new Date(`${dateStr}T00:00:00`).toLocaleDateString('zh-CN')}）`
}

async function loadContracts() {
  loading.value = true
  try {
    if (viewMode.value === 'trash') {
      contracts.value = await getTrashContracts()
      return
    }
    contracts.value = await getContracts({
      keyword: filters.keyword || undefined,
      contract_status: filters.status || undefined,
      risk: filters.risk || undefined,
      sort: filters.sort,
    })
    // 回收站角标
    try {
      trashCount.value = (await getTrashContracts()).length
    } catch {
      trashCount.value = 0
    }
  } finally {
    loading.value = false
  }
}

async function handleStartReview(contractId: number) {
  reviewLoading.value = contractId
  try {
    const res = await startReview(contractId)
    ElMessage.success('审查任务已启动')
    router.push(`/report/${contractId}/${res.review_session_id}`)
  } catch (err: any) {
    openPaywall(err)
  } finally {
    reviewLoading.value = null
  }
}

// ---------- 配额不足升级引导 ----------
const paywallVisible = ref(false)
const paywallReason = ref<'monthly_reviews' | 'page_limit'>('monthly_reviews')
const paywallUsed = ref<number>()
const paywallLimit = ref<number>()

function openPaywall(err: any) {
  const detail = err?.response?.data?.detail
  if (err?.response?.status === 402 && detail?.code === 'QUOTA_EXCEEDED') {
    paywallReason.value = detail.reason
    paywallUsed.value = detail.used
    paywallLimit.value = detail.limit
    paywallVisible.value = true
  }
}

function viewReport(contractId: number, sessionId: number) {
  router.push(`/report/${contractId}/${sessionId}`)
}

async function handleDelete(contractId: number) {
  await ElMessageBox.confirm('删除后将移入回收站，30 天内可恢复。', '删除确认', {
    type: 'warning',
    confirmButtonText: '移入回收站',
    cancelButtonText: '取消',
  })
  await deleteContract(contractId)
  ElMessage.success('已移入回收站')
  await loadContracts()
}

// ---------- 回收站 ----------
async function handleRestore(contractId: number) {
  await restoreContract(contractId)
  ElMessage.success('恢复成功')
  await loadContracts()
}

async function handlePurge(contractId: number) {
  await ElMessageBox.confirm('彻底删除后不可恢复（含历史版本与审查数据），确定继续？', '彻底删除', {
    type: 'error',
    confirmButtonText: '彻底删除',
    cancelButtonText: '取消',
  })
  await purgeContract(contractId)
  ElMessage.success('已彻底删除')
  await loadContracts()
}

// ---------- 在线预览 ----------
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewType = ref<'pdf' | 'image'>('pdf')
const previewBlobUrl = ref('')
const previewContract = ref<Contract | null>(null)

function canPreview(c: Contract) {
  return c.file_type === 'pdf' || c.file_type === 'image'
}

async function openPreview(c: Contract) {
  previewContract.value = c
  previewType.value = c.file_type === 'pdf' ? 'pdf' : 'image'
  previewVisible.value = true
  previewLoading.value = true
  try {
    const blob = await previewContractFile(c.id)
    revokePreview()
    previewBlobUrl.value = URL.createObjectURL(blob)
  } finally {
    previewLoading.value = false
  }
}

function revokePreview() {
  if (previewBlobUrl.value) {
    URL.revokeObjectURL(previewBlobUrl.value)
    previewBlobUrl.value = ''
  }
}

// ---------- 版本管理与重新上传 ----------
const versionsVisible = ref(false)
const versionsLoading = ref(false)
const versions = ref<ContractFileVersion[]>([])
const versionContractId = ref<number | null>(null)
const versionContractName = ref('')

const reuploadVisible = ref(false)
const reuploading = ref(false)
const reuploadFile = ref<File | null>(null)
const reuploadContract = ref<Contract | null>(null)

const ACCEPT = ['.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg']

function onMoreCommand(cmd: string, c: Contract) {
  if (cmd === 'delete') handleDelete(c.id)
  else if (cmd === 'versions') openVersions(c)
  else if (cmd === 'reupload') openReupload(c)
  else if (cmd === 'diff') openDiffReview(c)
}

// ---------- 对比审查 ----------
const diffVisible = ref(false)
const diffContract = ref<Contract | null>(null)
const diffVersions = ref<ContractFileVersion[]>([])
const diffBaseVersion = ref<number | null>(null)
const diffStarting = ref(false)

async function openDiffReview(c: Contract) {
  diffContract.value = c
  diffBaseVersion.value = null
  diffVisible.value = true
  try {
    diffVersions.value = await getContractVersions(c.id)
  } catch {
    diffVersions.value = []
  }
}

async function handleDiffReview() {
  if (!diffContract.value || !diffBaseVersion.value) return
  diffStarting.value = true
  try {
    const res = await startReview(diffContract.value.id, diffBaseVersion.value)
    ElMessage.success('对比审查任务已启动')
    diffVisible.value = false
    router.push(`/report/${diffContract.value.id}/${res.review_session_id}`)
  } catch (err: any) {
    openPaywall(err)
  } finally {
    diffStarting.value = false
  }
}

async function openVersions(c: Contract) {
  versionContractId.value = c.id
  versionContractName.value = c.filename
  versionsVisible.value = true
  versionsLoading.value = true
  try {
    versions.value = await getContractVersions(c.id)
  } finally {
    versionsLoading.value = false
  }
}

async function downloadVersion(version: number) {
  if (!versionContractId.value) return
  const blob = await downloadContractFile(versionContractId.value, version)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `v${version}-${versionContractName.value}`
  a.click()
  URL.revokeObjectURL(url)
}

function openReupload(c: Contract) {
  reuploadContract.value = c
  reuploadFile.value = null
  reuploadVisible.value = true
}

function onReuploadFile(file: any) {
  const raw: File = file.raw
  const ext = '.' + (raw.name.split('.').pop() || '').toLowerCase()
  if (!ACCEPT.includes(ext)) {
    ElMessage.warning(`不支持的文件格式 ${ext}，请上传 PDF / Word / 图片`)
    return
  }
  reuploadFile.value = raw
}

async function handleReupload() {
  if (!reuploadContract.value || !reuploadFile.value) return
  reuploading.value = true
  try {
    const res = await reuploadContractApi(reuploadContract.value.id, reuploadFile.value)
    ElMessage.success(res.message)
    reuploadVisible.value = false
    await loadContracts()
  } finally {
    reuploading.value = false
  }
}

function formatSize(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

onMounted(loadContracts)
</script>

<style scoped>
.dashboard {
  max-width: 1200px;
  margin: 0 auto;
}

/* ---------- 欢迎横幅 ---------- */
.welcome-banner {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 26px 32px;
  border-radius: var(--cg-radius-lg);
  background: var(--cg-gradient);
  color: #fff;
  overflow: hidden;
  margin-bottom: 20px;
}

.welcome-text h2 {
  font-size: 21px;
  font-weight: 700;
}

.welcome-text p {
  margin-top: 6px;
  font-size: 13px;
  opacity: 0.85;
}

.banner-btn {
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.35);
  z-index: 1;
}

.banner-btn:hover {
  background: rgba(255, 255, 255, 0.26);
}

.banner-deco {
  position: absolute;
  right: -60px;
  top: -80px;
  width: 260px;
  height: 260px;
  border-radius: 50%;
  border: 50px solid rgba(255, 255, 255, 0.08);
}

/* ---------- KPI ---------- */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 28px;
}

.kpi-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  background: #fff;
  border: 1px solid var(--cg-border);
  border-radius: var(--cg-radius);
  box-shadow: var(--cg-shadow-sm);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.kpi-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--cg-shadow);
}

.kpi-icon {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 11px;
  color: var(--kpi-color);
  background: color-mix(in srgb, var(--kpi-color) 12%, white);
}

.kpi-value {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: var(--cg-text);
  line-height: 1.2;
}

.kpi-label {
  font-size: 12px;
  color: var(--cg-text-muted);
}

/* ---------- 筛选工具栏 ---------- */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  margin-bottom: 20px;
}

.filter-search {
  max-width: 260px;
}

.filter-select {
  width: 132px;
}

.filter-spacer {
  flex: 1;
}

.trash-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}

.trash-banner .el-alert {
  flex: 1;
}

.trash-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ---------- 预览弹窗 ---------- */
.preview-body {
  height: 78vh;
  display: flex;
  justify-content: center;
}

.preview-frame {
  width: 100%;
  height: 100%;
  border: none;
  border-radius: 8px;
  background: #f5f5f7;
}

.preview-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

/* ---------- 版本与重新上传 ---------- */
.versions-tip {
  margin-top: 10px;
  font-size: 12px;
  color: var(--cg-text-muted);
}

.reupload-tip {
  font-size: 13px;
  color: var(--cg-text-secondary);
  margin: 0 0 12px;
}

.reupload-drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 18px;
  font-size: 13px;
  color: var(--cg-text-secondary);
}

.reupload-hint {
  color: var(--cg-text-muted);
}

/* ---------- 列表 ---------- */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.section-header h3 {
  font-size: 17px;
  font-weight: 700;
}

.empty-state {
  padding: 60px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.empty-icon {
  width: 84px;
  height: 84px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--cg-gradient-soft);
  color: var(--cg-primary);
  margin-bottom: 8px;
}

.empty-state h4 {
  font-size: 16px;
}

.empty-state p {
  font-size: 13px;
  color: var(--cg-text-muted);
  margin-bottom: 12px;
}

.contract-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.contract-card {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.contract-card.is-danger {
  border-top: 3px solid var(--cg-danger);
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.file-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.type-pdf {
  color: #dc2626;
  background: #fee2e2;
}

.type-docx, .type-doc {
  color: #2563eb;
  background: #dbeafe;
}

.type-png, .type-jpg, .type-jpeg {
  color: #7c3aed;
  background: #ede9fe;
}

.type-file {
  color: #64748b;
  background: #f1f5f9;
}

.card-filename {
  font-size: 15px;
  font-weight: 600;
  color: var(--cg-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-date {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--cg-text-muted);
}

.risk-strip {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  min-height: 24px;
}

/* 到期倒计时 */
.expiry-strip {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 8px;
  font-size: 11.5px;
  font-weight: 600;
  color: #f59e0b;
}

.expiry-strip .urgent {
  color: #ef4444;
}

.risk-chip {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 20px;
}

.risk-chip.high {
  color: #dc2626;
  background: #fef2f2;
}

.risk-chip.medium {
  color: #d97706;
  background: #fffbeb;
}

.risk-chip.low {
  color: #059669;
  background: #ecfdf5;
}

.risk-chip.none {
  color: #64748b;
  background: #f1f5f9;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: auto;
  padding-top: 6px;
  border-top: 1px dashed var(--cg-border);
}

@media (max-width: 960px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
