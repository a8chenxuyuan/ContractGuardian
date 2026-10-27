<template>
  <div class="admin-page">
    <div class="page-header">
      <h2>管理后台</h2>
      <p>平台运营、用户管理、知识库与安全审计</p>
    </div>

    <el-tabs v-model="activeTab" class="admin-tabs" @tab-change="onTabChange">
      <!-- ============ 数据概览 ============ -->
      <el-tab-pane label="数据概览" name="overview">
        <div class="stat-row">
          <div class="ov-card">
            <span class="ov-value">{{ stats?.user_total ?? '-' }}</span>
            <span class="ov-label">注册用户</span>
          </div>
          <div class="ov-card">
            <span class="ov-value">{{ stats?.contract_total ?? '-' }}</span>
            <span class="ov-label">合同总数</span>
          </div>
          <div class="ov-card">
            <span class="ov-value">{{ stats?.review_total ?? '-' }}</span>
            <span class="ov-label">审查次数</span>
          </div>
          <div class="ov-card">
            <span class="ov-value">{{ stats?.risk_levels?.high ?? '-' }}</span>
            <span class="ov-label">高风险发现</span>
          </div>
        </div>
        <el-row :gutter="20">
          <el-col :xs="24" :md="14">
            <div class="cg-card chart-card">
              <h4 class="card-title">近 7 日审查趋势</h4>
              <div ref="trendRef" class="chart-box" />
            </div>
          </el-col>
          <el-col :xs="24" :md="10">
            <div class="cg-card chart-card">
              <h4 class="card-title">风险等级分布</h4>
              <div ref="pieRef" class="chart-box" />
            </div>
          </el-col>
        </el-row>
        <el-row>
          <el-col :span="24">
            <div class="cg-card chart-card">
              <h4 class="card-title">高频风险类型 Top 5</h4>
              <div ref="barRef" class="chart-box" />
            </div>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- ============ 用户管理 ============ -->
      <el-tab-pane label="用户管理" name="users">
        <div class="toolbar">
          <el-input
            v-model="userKeyword"
            placeholder="搜索邮箱 / 昵称"
            clearable
            style="width: 240px"
            @keyup.enter="loadUsers"
            @clear="loadUsers"
          >
            <template #prefix><el-icon><search /></el-icon></template>
          </el-input>
          <el-button round @click="loadUsers">查询</el-button>
        </div>
        <el-table :data="users" v-loading="usersLoading" stripe>
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="email" label="邮箱" min-width="200" show-overflow-tooltip />
          <el-table-column prop="nickname" label="昵称" width="120" />
          <el-table-column label="角色" width="150">
            <template #default="{ row }">
              <el-tag v-if="row.is_admin" type="danger" size="small">管理员</el-tag>
              <el-tag v-else-if="row.is_member" type="warning" size="small">会员</el-tag>
              <el-tag v-else type="info" size="small">免费版</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
                {{ row.is_active ? '正常' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="contract_count" label="合同" width="70" align="center" />
          <el-table-column prop="review_count" label="审查" width="70" align="center" />
          <el-table-column label="注册时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openRoleDialog(row)">角色</el-button>
              <el-button link :type="row.is_active ? 'warning' : 'success'" size="small" @click="toggleUser(row)">
                {{ row.is_active ? '禁用' : '启用' }}
              </el-button>
              <el-button link type="primary" size="small" @click="resetPwd(row)">重置密码</el-button>
              <el-button link type="danger" size="small" @click="removeUser(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination
            v-model:current-page="userPage"
            :page-size="userPageSize"
            :total="userTotal"
            layout="total, prev, pager, next"
            @current-change="loadUsers"
          />
        </div>
      </el-tab-pane>

      <!-- ============ 审查记录 ============ -->
      <el-tab-pane label="审查记录" name="reviews">
        <el-table :data="reviews" v-loading="reviewsLoading" stripe>
          <el-table-column prop="id" label="会话ID" width="80" />
          <el-table-column prop="filename" label="合同文件" min-width="220" show-overflow-tooltip />
          <el-table-column prop="owner" label="所有者" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="reviewTagType(row.status)" size="small">{{ reviewText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="发起时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="完成时间" width="170">
            <template #default="{ row }">{{ row.completed_at ? fmtTime(row.completed_at) : '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                size="small"
                :disabled="row.status !== 'completed'"
                @click="router.push(`/report/${row.contract_id}/${row.id}`)"
              >
                查看报告
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination
            v-model:current-page="reviewPage"
            :page-size="reviewPageSize"
            :total="reviewTotal"
            layout="total, prev, pager, next"
            @current-change="loadReviews"
          />
        </div>
      </el-tab-pane>

      <!-- ============ 人工复核 ============ -->
      <el-tab-pane label="人工复核" name="human">
        <div class="toolbar">
          <el-radio-group v-model="humanStatus" @change="loadHumanReviews">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button value="pending">待处理</el-radio-button>
            <el-radio-button value="approved">已通过</el-radio-button>
            <el-radio-button value="rejected">已驳回</el-radio-button>
          </el-radio-group>
        </div>
        <el-table :data="humanReviews" v-loading="humanLoading" stripe>
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="review_session_id" label="审查会话" width="90" />
          <el-table-column prop="reason" label="复核原因" min-width="260" show-overflow-tooltip />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="humanTagType(row.status)" size="small">{{ humanText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="提交时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <template v-if="row.status === 'pending'">
                <el-button link type="success" size="small" @click="resolveReview(row, 'approve')">通过</el-button>
                <el-button link type="danger" size="small" @click="resolveReview(row, 'reject')">驳回</el-button>
              </template>
              <span v-else class="resolved-comment">{{ row.comment || '-' }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============ 工具审批（HITL） ============ -->
      <el-tab-pane label="工具审批" name="approvals">
        <div class="toolbar">
          <el-button round @click="loadApprovals">刷新</el-button>
          <span class="resolved-comment">Agent 调用受控工具时在此挂起等待，裁决后立即恢复执行</span>
        </div>
        <el-table :data="approvals" v-loading="approvalsLoading" stripe>
          <el-table-column prop="tool" label="工具" width="180" show-overflow-tooltip />
          <el-table-column prop="agent_name" label="发起 Agent" width="140" />
          <el-table-column prop="input_preview" label="入参摘要" min-width="280" show-overflow-tooltip />
          <el-table-column label="等待时长" width="110">
            <template #default="{ row }">{{ waitSeconds(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="success" size="small" @click="resolveApproval(row, 'approve')">放行</el-button>
              <el-button link type="danger" size="small" @click="resolveApproval(row, 'deny')">拒绝</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============ 知识库 ============ -->
      <el-tab-pane label="知识库" name="knowledge">
        <el-tabs v-model="kbTab" type="card" class="kb-tabs">
          <!-- 法条 -->
          <el-tab-pane label="法律法规" name="articles">
            <div class="toolbar">
              <el-input
                v-model="articleKeyword"
                placeholder="搜索法名 / 条号 / 内容"
                clearable
                style="width: 240px"
                @keyup.enter="loadArticles"
                @clear="loadArticles"
              />
              <el-button round @click="loadArticles">查询</el-button>
              <div class="toolbar-right">
                <el-button round @click="openImportDialog">
                  <el-icon style="margin-right: 4px"><upload-filled /></el-icon>批量导入
                </el-button>
                <el-button type="primary" round @click="openArticleDialog()">新增法条</el-button>
              </div>
            </div>
            <el-table :data="articles" v-loading="articlesLoading" stripe>
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column prop="law_name" label="法名" min-width="220" show-overflow-tooltip />
              <el-table-column prop="article_number" label="条号" width="100" />
              <el-table-column prop="article_title" label="标题" min-width="160" show-overflow-tooltip />
              <el-table-column prop="category" label="分类" width="110" />
              <el-table-column label="操作" width="130" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="openArticleDialog(row)">编辑</el-button>
                  <el-button link type="danger" size="small" @click="removeArticle(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="pager">
              <el-pagination
                v-model:current-page="articlePage"
                :page-size="articlePageSize"
                :total="articleTotal"
                layout="total, prev, pager, next"
                @current-change="loadArticles"
              />
            </div>
          </el-tab-pane>

          <!-- 案例 -->
          <el-tab-pane label="典型案例" name="cases">
            <div class="toolbar">
              <el-input
                v-model="caseKeyword"
                placeholder="搜索标题 / 摘要"
                clearable
                style="width: 240px"
                @keyup.enter="loadCases"
                @clear="loadCases"
              />
              <el-button round @click="loadCases">查询</el-button>
              <div class="toolbar-right">
                <el-button type="primary" round @click="openCaseDialog()">新增案例</el-button>
              </div>
            </div>
            <el-table :data="cases" v-loading="casesLoading" stripe>
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
              <el-table-column prop="court" label="法院" width="160" show-overflow-tooltip />
              <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip />
              <el-table-column label="操作" width="130" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="openCaseDialog(row)">编辑</el-button>
                  <el-button link type="danger" size="small" @click="removeCase(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="pager">
              <el-pagination
                v-model:current-page="casePage"
                :page-size="casePageSize"
                :total="caseTotal"
                layout="total, prev, pager, next"
                @current-change="loadCases"
              />
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-tab-pane>

      <!-- ============ 审计日志 ============ -->
      <el-tab-pane label="审计日志" name="audit">
        <div class="toolbar">
          <el-select v-model="auditAction" placeholder="操作类型" clearable style="width: 140px" @change="loadAuditLogs">
            <el-option label="登录" value="LOGIN" />
            <el-option label="POST" value="POST" />
            <el-option label="PUT" value="PUT" />
            <el-option label="DELETE" value="DELETE" />
          </el-select>
          <el-input
            v-model="auditKeyword"
            placeholder="搜索用户 / 资源路径"
            clearable
            style="width: 240px"
            @keyup.enter="loadAuditLogs"
            @clear="loadAuditLogs"
          />
          <el-button round @click="loadAuditLogs">查询</el-button>
        </div>
        <el-table :data="auditLogs" v-loading="auditLoading" stripe>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="email" label="用户" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.email || '匿名' }}</template>
          </el-table-column>
          <el-table-column prop="action" label="操作" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.action === 'DELETE' ? 'danger' : row.action === 'LOGIN' ? 'success' : 'primary'">
                {{ row.action }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="resource" label="资源路径" min-width="260" show-overflow-tooltip />
          <el-table-column prop="ip" label="IP" width="130" />
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination
            v-model:current-page="auditPage"
            :page-size="auditPageSize"
            :total="auditTotal"
            layout="total, prev, pager, next"
            @current-change="loadAuditLogs"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 角色编辑对话框 -->
    <el-dialog v-model="roleDialog.visible" title="调整用户角色" width="420px">
      <div class="role-line">
        <span>邮箱：{{ roleDialog.email }}</span>
      </div>
      <div class="role-line">
        <el-switch v-model="roleDialog.is_admin" active-text="管理员" />
      </div>
      <div class="role-line">
        <el-switch v-model="roleDialog.is_member" active-text="会员" />
      </div>
      <template #footer>
        <el-button @click="roleDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>

    <!-- 法条编辑对话框 -->
    <el-dialog v-model="articleDialog.visible" :title="articleDialog.id ? '编辑法条' : '新增法条'" width="600px">
      <el-form label-width="70px">
        <el-form-item label="法名" required>
          <el-input v-model="articleDialog.law_name" placeholder="如《中华人民共和国劳动合同法》" />
        </el-form-item>
        <el-form-item label="条号" required>
          <el-input v-model="articleDialog.article_number" placeholder="如第十七条" />
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="articleDialog.article_title" placeholder="条款标题" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="articleDialog.category" placeholder="如 劳动合同法 / 民法典" />
        </el-form-item>
        <el-form-item label="条文" required>
          <el-input v-model="articleDialog.article_text" type="textarea" :rows="6" placeholder="法条全文" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="articleDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="articleDialog.saving" @click="saveArticle">保存并向量化</el-button>
      </template>
    </el-dialog>

    <!-- 案例编辑对话框 -->
    <el-dialog v-model="caseDialog.visible" :title="caseDialog.id ? '编辑案例' : '新增案例'" width="600px">
      <el-form label-width="70px">
        <el-form-item label="标题" required>
          <el-input v-model="caseDialog.title" />
        </el-form-item>
        <el-form-item label="法院">
          <el-input v-model="caseDialog.court" />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="caseDialog.summary" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="裁判要旨">
          <el-input v-model="caseDialog.verdict" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="caseDialog.source_url" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="caseDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="caseDialog.saving" @click="saveCase">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入对话框 -->
    <el-dialog v-model="importDialog.visible" title="批量导入法条" width="640px">
      <el-alert type="info" :closable="false" class="import-tip">
        支持 JSON 数组，字段：law_name（必填）、article_number（必填）、article_text（必填）、article_title、category。
        按「法名+条号」去重，已存在则更新。
      </el-alert>
      <el-upload
        :auto-upload="false"
        :show-file-list="false"
        accept=".json"
        :on-change="onImportFile"
        class="import-upload"
      >
        <el-button round>选择 JSON 文件</el-button>
      </el-upload>
      <el-input
        v-model="importDialog.text"
        type="textarea"
        :rows="10"
        placeholder='或直接粘贴 JSON，如：[{"law_name":"《...》","article_number":"第X条","article_text":"..."}]'
      />
      <template #footer>
        <el-button @click="importDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="importDialog.saving" @click="doImport">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import * as echarts from 'echarts'
import { Search, UploadFilled } from '@element-plus/icons-vue'
import type { AdminStats, AdminUser } from '@/types'
import {
  approveToolCall, createArticle, createCase, deleteArticle, deleteCase, deleteUser,
  denyToolCall, getAdminStats, importKnowledgeArticles, listAllReviews, listApprovals,
  listArticles, listAuditLogs, listCases, listHumanReviews, listUsers, resetUserPassword,
  resolveHumanReview, setUserRole, setUserStatus, updateArticle, updateCase,
} from '@/api/admin'
import type { ApprovalItem, HumanReviewItem } from '@/api/admin'

const router = useRouter()

// ---------- 通用 ----------
function fmtTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function reviewText(status: string) {
  const map: Record<string, string> = { completed: '已完成', running: '审查中', pending: '排队中', failed: '失败' }
  return map[status] || status
}

function reviewTagType(status: string) {
  const map: Record<string, 'success' | 'warning' | 'info' | 'danger'> = {
    completed: 'success', running: 'warning', pending: 'info', failed: 'danger',
  }
  return map[status] || 'info'
}

function humanText(status: string) {
  const map: Record<string, string> = { pending: '待处理', approved: '已通过', rejected: '已驳回' }
  return map[status] || status
}

function humanTagType(status: string) {
  const map: Record<string, 'warning' | 'success' | 'danger'> = { pending: 'warning', approved: 'success', rejected: 'danger' }
  return map[status] || 'info'
}

// ---------- 数据概览 ----------
const activeTab = ref('overview')
const stats = ref<AdminStats | null>(null)
const trendRef = ref<HTMLElement>()
const pieRef = ref<HTMLElement>()
const barRef = ref<HTMLElement>()
let chartInstances: echarts.ECharts[] = []

async function loadStats() {
  stats.value = await getAdminStats()
  await renderCharts()
}

async function renderCharts() {
  await nextTick()
  chartInstances.forEach((c) => c.dispose())
  chartInstances = []
  const primary = '#4f46e5'
  const palette = ['#4f46e5', '#7c3aed', '#f43f5e', '#f59e0b', '#10b981']

  if (trendRef.value && stats.value) {
    const chart = echarts.init(trendRef.value)
    chart.setOption({
      grid: { left: 40, right: 20, top: 20, bottom: 30 },
      xAxis: { type: 'category', data: stats.value.review_trend.map((t) => t.date) },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{
        type: 'line', smooth: true, data: stats.value.review_trend.map((t) => t.count),
        lineStyle: { color: primary, width: 3 }, itemStyle: { color: primary },
        areaStyle: { color: 'rgba(79, 70, 229, 0.12)' },
      }],
      tooltip: { trigger: 'axis' },
    })
    chartInstances.push(chart)
  }
  if (pieRef.value && stats.value) {
    const rl = stats.value.risk_levels
    const chart = echarts.init(pieRef.value)
    chart.setOption({
      series: [{
        type: 'pie', radius: ['45%', '70%'],
        data: [
          { name: '高风险', value: rl.high, itemStyle: { color: '#f43f5e' } },
          { name: '中风险', value: rl.medium, itemStyle: { color: '#f59e0b' } },
          { name: '低风险', value: rl.low, itemStyle: { color: '#10b981' } },
        ],
        label: { formatter: '{b}: {c}' },
      }],
      tooltip: { trigger: 'item' },
    })
    chartInstances.push(chart)
  }
  if (barRef.value && stats.value) {
    const chart = echarts.init(barRef.value)
    chart.setOption({
      grid: { left: 160, right: 30, top: 10, bottom: 30 },
      xAxis: { type: 'value', minInterval: 1 },
      yAxis: { type: 'category', data: stats.value.top_risk_types.map((t) => t.type).reverse() },
      series: [{
        type: 'bar',
        data: stats.value.top_risk_types.map((t) => t.count).reverse(),
        itemStyle: { color: '#7c3aed', borderRadius: [0, 6, 6, 0] },
        barWidth: 18,
      }],
      tooltip: { trigger: 'axis' },
    })
    chartInstances.push(chart)
  }
}

function onTabChange(tab: string) {
  if (tab === 'overview') renderCharts()
  if (tab === 'users' && !users.value.length) loadUsers()
  if (tab === 'reviews' && !reviews.value.length) loadReviews()
  if (tab === 'human' && !humanReviews.value.length) loadHumanReviews()
  if (tab === 'approvals' && !approvals.value.length) loadApprovals()
  if (tab === 'knowledge' && !articles.value.length) { loadArticles(); loadCases() }
  if (tab === 'audit' && !auditLogs.value.length) loadAuditLogs()
}

// ---------- 用户管理 ----------
const users = ref<AdminUser[]>([])
const usersLoading = ref(false)
const userKeyword = ref('')
const userPage = ref(1)
const userPageSize = 20
const userTotal = ref(0)

async function loadUsers() {
  usersLoading.value = true
  try {
    const res = await listUsers({
      skip: (userPage.value - 1) * userPageSize,
      limit: userPageSize,
      keyword: userKeyword.value || undefined,
    })
    users.value = res.items
    userTotal.value = res.total
  } finally {
    usersLoading.value = false
  }
}

const roleDialog = reactive({ visible: false, id: 0, email: '', is_admin: false, is_member: false })

function openRoleDialog(row: AdminUser) {
  roleDialog.id = row.id
  roleDialog.email = row.email
  roleDialog.is_admin = row.is_admin
  roleDialog.is_member = row.is_member
  roleDialog.visible = true
}

async function saveRole() {
  await setUserRole(roleDialog.id, { is_admin: roleDialog.is_admin, is_member: roleDialog.is_member })
  roleDialog.visible = false
  ElMessage.success('角色已更新')
  await loadUsers()
}

async function toggleUser(row: AdminUser) {
  await setUserStatus(row.id, !row.is_active)
  ElMessage.success(row.is_active ? '已禁用' : '已启用')
  await loadUsers()
}

async function resetPwd(row: AdminUser) {
  const { value } = await ElMessageBox.prompt(`为 ${row.email} 设置新密码（至少 6 位）`, '重置密码', {
    inputPattern: /^.{6,}$/,
    inputErrorMessage: '密码至少 6 位',
  })
  await resetUserPassword(row.id, value)
  ElMessage.success('密码已重置')
}

async function removeUser(row: AdminUser) {
  await ElMessageBox.confirm(`确定删除用户 ${row.email}？该操作不可恢复。`, '删除用户', { type: 'warning' })
  await deleteUser(row.id)
  ElMessage.success('用户已删除')
  await loadUsers()
}

// ---------- 审查记录 ----------
const reviews = ref<Awaited<ReturnType<typeof listAllReviews>>['items']>([])
const reviewsLoading = ref(false)
const reviewPage = ref(1)
const reviewPageSize = 20
const reviewTotal = ref(0)

async function loadReviews() {
  reviewsLoading.value = true
  try {
    const res = await listAllReviews({
      skip: (reviewPage.value - 1) * reviewPageSize,
      limit: reviewPageSize,
    })
    reviews.value = res.items
    reviewTotal.value = res.total
  } finally {
    reviewsLoading.value = false
  }
}

// ---------- 人工复核 ----------
const humanReviews = ref<HumanReviewItem[]>([])
const humanLoading = ref(false)
const humanStatus = ref('')

async function loadHumanReviews() {
  humanLoading.value = true
  try {
    humanReviews.value = await listHumanReviews(humanStatus.value ? { status: humanStatus.value } : undefined)
  } finally {
    humanLoading.value = false
  }
}

async function resolveReview(row: HumanReviewItem, action: 'approve' | 'reject') {
  const { value } = await ElMessageBox.prompt(
    action === 'approve' ? '通过该复核任务，可填写处理意见' : '驳回该复核任务，请填写驳回原因',
    action === 'approve' ? '通过复核' : '驳回复核',
    { inputPlaceholder: '处理意见（可选）' },
  )
  await resolveHumanReview(row.id, action, value || undefined)
  ElMessage.success('处理成功')
  await loadHumanReviews()
}

// ---------- 工具审批（HITL） ----------
const approvals = ref<ApprovalItem[]>([])
const approvalsLoading = ref(false)

async function loadApprovals() {
  approvalsLoading.value = true
  try {
    approvals.value = await listApprovals()
  } finally {
    approvalsLoading.value = false
  }
}

function waitSeconds(createdAt: number): string {
  const s = Math.max(0, Math.round(Date.now() / 1000 - createdAt))  // 后端存 unix 秒
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`
}

async function resolveApproval(row: ApprovalItem, action: 'approve' | 'deny') {
  if (action === 'deny') {
    await ElMessageBox.confirm(`确认拒绝工具 ${row.tool} 的本次调用？Agent 将收到拒绝并换路径处理。`, '拒绝工具调用', { type: 'warning' })
  }
  if (action === 'approve') await approveToolCall(row.approval_id)
  else await denyToolCall(row.approval_id)
  ElMessage.success(action === 'approve' ? '已放行，等待中的调用已恢复执行' : '已拒绝')
  await loadApprovals()
}

// ---------- 知识库：法条 ----------
const kbTab = ref('articles')
const articles = ref<Awaited<ReturnType<typeof listArticles>>['items']>([])
const articlesLoading = ref(false)
const articleKeyword = ref('')
const articlePage = ref(1)
const articlePageSize = 20
const articleTotal = ref(0)

async function loadArticles() {
  articlesLoading.value = true
  try {
    const res = await listArticles({
      skip: (articlePage.value - 1) * articlePageSize,
      limit: articlePageSize,
      keyword: articleKeyword.value || undefined,
    })
    articles.value = res.items
    articleTotal.value = res.total
  } finally {
    articlesLoading.value = false
  }
}

const articleDialog = reactive({
  visible: false, saving: false, id: 0,
  law_name: '', article_number: '', article_title: '', article_text: '', category: '',
})

function openArticleDialog(row?: (typeof articles.value)[number]) {
  articleDialog.id = row?.id || 0
  articleDialog.law_name = row?.law_name || ''
  articleDialog.article_number = row?.article_number || ''
  articleDialog.article_title = row?.article_title || ''
  articleDialog.article_text = row?.article_text || ''
  articleDialog.category = row?.category || ''
  articleDialog.visible = true
}

async function saveArticle() {
  if (!articleDialog.law_name || !articleDialog.article_number || !articleDialog.article_text) {
    ElMessage.warning('法名、条号、条文为必填项')
    return
  }
  articleDialog.saving = true
  try {
    const payload = {
      law_name: articleDialog.law_name,
      article_number: articleDialog.article_number,
      article_title: articleDialog.article_title,
      article_text: articleDialog.article_text,
      category: articleDialog.category,
    }
    const res = articleDialog.id ? await updateArticle(articleDialog.id, payload) : await createArticle(payload)
    ElMessage.success(res.vectorized ? `已保存并向量化 ${res.vectorized} 个文本块` : '已保存（向量库不可用，仅入库）')
    articleDialog.visible = false
    await loadArticles()
  } finally {
    articleDialog.saving = false
  }
}

async function removeArticle(row: (typeof articles.value)[number]) {
  await ElMessageBox.confirm(`确定删除「${row.law_name} ${row.article_number}」？将同步清理向量数据。`, '删除法条', { type: 'warning' })
  await deleteArticle(row.id)
  ElMessage.success('已删除')
  await loadArticles()
}

// ---------- 知识库：案例 ----------
const cases = ref<Awaited<ReturnType<typeof listCases>>['items']>([])
const casesLoading = ref(false)
const caseKeyword = ref('')
const casePage = ref(1)
const casePageSize = 20
const caseTotal = ref(0)

async function loadCases() {
  casesLoading.value = true
  try {
    const res = await listCases({
      skip: (casePage.value - 1) * casePageSize,
      limit: casePageSize,
      keyword: caseKeyword.value || undefined,
    })
    cases.value = res.items
    caseTotal.value = res.total
  } finally {
    casesLoading.value = false
  }
}

const caseDialog = reactive({
  visible: false, saving: false, id: 0,
  title: '', court: '', summary: '', verdict: '', source_url: '',
})

function openCaseDialog(row?: (typeof cases.value)[number]) {
  caseDialog.id = row?.id || 0
  caseDialog.title = row?.title || ''
  caseDialog.court = row?.court || ''
  caseDialog.summary = row?.summary || ''
  caseDialog.verdict = row?.verdict || ''
  caseDialog.source_url = row?.source_url || ''
  caseDialog.visible = true
}

async function saveCase() {
  if (!caseDialog.title) {
    ElMessage.warning('标题为必填项')
    return
  }
  caseDialog.saving = true
  try {
    const payload = {
      title: caseDialog.title, court: caseDialog.court, summary: caseDialog.summary,
      verdict: caseDialog.verdict, source_url: caseDialog.source_url,
    }
    if (caseDialog.id) await updateCase(caseDialog.id, payload)
    else await createCase(payload)
    ElMessage.success('已保存')
    caseDialog.visible = false
    await loadCases()
  } finally {
    caseDialog.saving = false
  }
}

async function removeCase(row: (typeof cases.value)[number]) {
  await ElMessageBox.confirm(`确定删除案例「${row.title}」？`, '删除案例', { type: 'warning' })
  await deleteCase(row.id)
  ElMessage.success('已删除')
  await loadCases()
}

// ---------- 批量导入 ----------
const importDialog = reactive({ visible: false, saving: false, text: '' })

function openImportDialog() {
  importDialog.text = ''
  importDialog.visible = true
}

function onImportFile(file: UploadFile) {
  const reader = new FileReader()
  reader.onload = () => {
    importDialog.text = String(reader.result || '')
  }
  reader.readAsText(file.raw as File)
}

async function doImport() {
  let parsed: unknown
  try {
    parsed = JSON.parse(importDialog.text)
  } catch {
    ElMessage.error('JSON 格式错误，请检查')
    return
  }
  if (!Array.isArray(parsed) || !parsed.length) {
    ElMessage.warning('请提供非空的 JSON 数组')
    return
  }
  importDialog.saving = true
  try {
    const res = await importKnowledgeArticles(parsed as Record<string, unknown>[])
    ElMessage.success(`导入完成：新增 ${res.imported}，更新 ${res.updated}，跳过 ${res.skipped}，向量化 ${res.vectorized} 条`)
    importDialog.visible = false
    await loadArticles()
  } finally {
    importDialog.saving = false
  }
}

// ---------- 审计日志 ----------
const auditLogs = ref<Awaited<ReturnType<typeof listAuditLogs>>['items']>([])
const auditLoading = ref(false)
const auditAction = ref('')
const auditKeyword = ref('')
const auditPage = ref(1)
const auditPageSize = 20
const auditTotal = ref(0)

async function loadAuditLogs() {
  auditLoading.value = true
  try {
    const res = await listAuditLogs({
      skip: (auditPage.value - 1) * auditPageSize,
      limit: auditPageSize,
      action: auditAction.value || undefined,
      keyword: auditKeyword.value || undefined,
    })
    auditLogs.value = res.items
    auditTotal.value = res.total
  } finally {
    auditLoading.value = false
  }
}

onMounted(loadStats)
</script>

<style scoped>
.admin-page {
  max-width: 1280px;
  margin: 0 auto;
}

.page-header h2 {
  font-size: 20px;
  margin: 0 0 4px;
}

.page-header p {
  font-size: 13px;
  color: var(--cg-text-muted);
  margin: 0 0 16px;
}

.admin-tabs {
  background: #fff;
  border: 1px solid var(--cg-border);
  border-radius: var(--cg-radius);
  padding: 8px 20px 20px;
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

.ov-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 20px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(79, 70, 229, 0.06), rgba(124, 58, 237, 0.06));
  border: 1px solid rgba(79, 70, 229, 0.12);
}

.ov-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--cg-text);
}

.ov-label {
  font-size: 12px;
  color: var(--cg-text-muted);
}

.chart-card {
  padding: 18px;
  margin-bottom: 20px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 12px;
}

.chart-box {
  height: 260px;
  width: 100%;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.toolbar-right {
  margin-left: auto;
  display: flex;
  gap: 10px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.kb-tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.role-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  font-size: 14px;
}

.import-tip {
  margin-bottom: 12px;
}

.import-upload {
  margin-bottom: 12px;
}

.resolved-comment {
  font-size: 12px;
  color: var(--cg-text-muted);
}

@media (max-width: 900px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
