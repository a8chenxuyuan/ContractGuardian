<template>
  <div class="tpl-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">合同模板库</h2>
        <p class="page-sub">预置标准范本开箱即用，也可上传自己的常用模板统一管理</p>
      </div>
      <el-button type="primary" round @click="openUpload">
        <el-icon style="margin-right: 4px"><plus /></el-icon>
        上传模板
      </el-button>
    </div>

    <div class="cg-card toolbar">
      <el-input
        v-model="keyword"
        class="search-input"
        placeholder="搜索模板名称、分类或适用场景，回车检索"
        clearable
        :prefix-icon="Search"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <div class="cat-chips">
        <span class="cat-chip" :class="{ active: activeCategory === '' }" @click="onCategory('')">
          全部
        </span>
        <span
          class="cat-chip"
          :class="{ active: mineOnly }"
          @click="onMineToggle"
        >
          我的模板
        </span>
        <span
          v-for="c in categories"
          :key="c.category"
          class="cat-chip"
          :class="{ active: activeCategory === c.category }"
          @click="onCategory(c.category)"
        >
          {{ c.category }}
          <em>{{ c.count }}</em>
        </span>
      </div>
    </div>

    <div v-if="loading" class="cg-card empty-tip">加载中…</div>
    <div v-else-if="!items.length" class="cg-card empty-tip">暂无匹配的模板</div>
    <div v-else class="tpl-grid">
      <div v-for="item in items" :key="item.id" class="cg-card tpl-card">
        <div class="tpl-head">
          <span class="tpl-name">{{ item.name }}</span>
          <el-tag v-if="item.is_preset" size="small" effect="plain" round>预置</el-tag>
          <el-tag v-else size="small" type="success" effect="plain" round>我的</el-tag>
        </div>
        <div class="tpl-meta">
          <el-tag size="small" effect="plain" round class="tpl-cat">{{ item.category }}</el-tag>
          <span class="tpl-usage">{{ item.usage_count }} 次下载</span>
        </div>
        <p class="tpl-scene">{{ item.scene || '暂无场景说明' }}</p>
        <div class="tpl-actions">
          <el-button link type="primary" @click="openDetail(item)">查看全文</el-button>
          <el-button link type="primary" :loading="downloading === item.id" @click="onDownload(item)">
            下载
          </el-button>
          <el-button v-if="!item.is_preset" link type="danger" @click="onDelete(item)">删除</el-button>
        </div>
      </div>
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

    <el-dialog v-model="detailVisible" :title="detail?.name" width="720px" top="6vh">
      <div v-if="detail" class="detail-body">
        <div class="detail-meta">
          <el-tag size="small" effect="plain" round>{{ detail.category }}</el-tag>
          <span class="detail-usage">{{ detail.usage_count }} 次下载</span>
        </div>
        <p v-if="detail.scene" class="detail-scene">{{ detail.scene }}</p>
        <pre class="tpl-fulltext">{{ detail.content }}</pre>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button v-if="detail" type="primary" :loading="downloading === detail.id" @click="onDownload(detail)">
          下载 docx
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="uploadVisible" title="上传自定义模板" width="640px" top="6vh">
      <el-form label-position="top" class="upload-form">
        <el-form-item label="模板名称" required>
          <el-input v-model="form.name" maxlength="255" placeholder="如：软件开发合同（自有版本）" />
        </el-form-item>
        <el-form-item label="分类" required>
          <el-select v-model="form.category" filterable allow-create placeholder="选择或输入分类">
            <el-option v-for="c in presetCategories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="适用场景">
          <el-input v-model="form.scene" maxlength="500" placeholder="一句话描述什么场景用这份模板" />
        </el-form-item>
        <el-form-item label="模板全文" required>
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="14"
            maxlength="60000"
            show-word-limit
            placeholder="粘贴模板全文（至少 50 字）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="onUpload">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import {
  createTemplate,
  deleteTemplate,
  downloadTemplate,
  getTemplate,
  listTemplateCategories,
  listTemplates,
} from '@/api/template'
import type { ContractTemplate } from '@/api/template'

const presetCategories = ['租赁类', '劳务类', '买卖类', '服务类', '金融类', '合作类']

const items = ref<ContractTemplate[]>([])
const categories = ref<{ category: string; count: number }[]>([])
const total = ref(0)
const keyword = ref('')
const activeCategory = ref('')
const mineOnly = ref(false)
const page = ref(1)
const pageSize = 12
const loading = ref(false)
const downloading = ref<number | null>(null)

const detail = ref<ContractTemplate | null>(null)
const detailVisible = ref(false)

const uploadVisible = ref(false)
const uploading = ref(false)
const form = ref({ name: '', category: '', scene: '', content: '' })

async function load() {
  loading.value = true
  try {
    const res = await listTemplates({
      skip: (page.value - 1) * pageSize,
      limit: pageSize,
      keyword: keyword.value || undefined,
      category: activeCategory.value || undefined,
      mine: mineOnly.value || undefined,
    })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadCategories() {
  categories.value = await listTemplateCategories()
}

function onSearch() {
  page.value = 1
  load()
}

function onCategory(category: string) {
  activeCategory.value = category
  mineOnly.value = false
  page.value = 1
  load()
}

function onMineToggle() {
  mineOnly.value = !mineOnly.value
  if (mineOnly.value) activeCategory.value = ''
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

async function openDetail(item: ContractTemplate) {
  const full = await getTemplate(item.id)
  detail.value = full
  detailVisible.value = true
}

async function onDownload(item: ContractTemplate) {
  downloading.value = item.id
  try {
    const blob = await downloadTemplate(item.id)
    const url = window.URL.createObjectURL(new Blob([blob]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `${item.name}.docx`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success('已开始下载')
  } finally {
    downloading.value = null
  }
}

async function onDelete(item: ContractTemplate) {
  await ElMessageBox.confirm(`确定删除模板「${item.name}」？删除后不可恢复。`, '删除确认', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
  await deleteTemplate(item.id)
  ElMessage.success('已删除')
  await Promise.all([load(), loadCategories()])
}

function openUpload() {
  form.value = { name: '', category: '', scene: '', content: '' }
  uploadVisible.value = true
}

async function onUpload() {
  if (form.value.name.trim().length < 2) {
    ElMessage.warning('请填写模板名称')
    return
  }
  if (!form.value.category.trim()) {
    ElMessage.warning('请选择或输入分类')
    return
  }
  if (form.value.content.trim().length < 50) {
    ElMessage.warning('模板全文至少 50 字')
    return
  }
  uploading.value = true
  try {
    await createTemplate({
      name: form.value.name.trim(),
      category: form.value.category.trim(),
      scene: form.value.scene.trim() || undefined,
      content: form.value.content,
    })
    ElMessage.success('模板已保存')
    uploadVisible.value = false
    mineOnly.value = true
    activeCategory.value = ''
    page.value = 1
    await Promise.all([load(), loadCategories()])
  } finally {
    uploading.value = false
  }
}

onMounted(() => {
  loadCategories()
  load()
})
</script>

<style scoped>
.tpl-page {
  max-width: 1080px;
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

.toolbar {
  padding: 16px 20px;
  margin-bottom: 16px;
}

.search-input {
  max-width: 420px;
}

.cat-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.cat-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 13px;
  color: var(--cg-text-secondary);
  background: #f1f5f9;
  cursor: pointer;
  transition: all 0.2s;
  user-select: none;
}

.cat-chip em {
  font-style: normal;
  font-size: 12px;
  color: var(--cg-text-muted);
}

.cat-chip:hover {
  background: #e2e8f0;
}

.cat-chip.active {
  background: var(--cg-gradient-soft, #eef2ff);
  color: var(--cg-primary);
  font-weight: 600;
}

.empty-tip {
  color: var(--cg-text-muted);
  font-size: 13px;
  text-align: center;
  padding: 56px 0;
}

.tpl-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.tpl-card {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tpl-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tpl-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--cg-text);
}

.tpl-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tpl-cat {
  color: var(--cg-text-muted);
}

.tpl-usage {
  font-size: 12px;
  color: var(--cg-text-muted);
}

.tpl-scene {
  font-size: 13px;
  color: var(--cg-text-secondary);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tpl-actions {
  display: flex;
  gap: 4px;
  margin-top: auto;
  padding-top: 6px;
  border-top: 1px solid #f1f5f9;
}

.pager {
  display: flex;
  justify-content: center;
  padding-top: 16px;
}

.detail-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.detail-usage {
  font-size: 12px;
  color: var(--cg-text-muted);
}

.detail-scene {
  font-size: 13px;
  color: var(--cg-text-secondary);
}

.tpl-fulltext {
  font-family: inherit;
  font-size: 13px;
  line-height: 1.8;
  color: var(--cg-text-secondary);
  white-space: pre-wrap;
  background: #f8fafc;
  border-radius: 8px;
  padding: 16px;
  max-height: 55vh;
  overflow: auto;
  margin: 0;
}

.upload-form :deep(.el-select) {
  width: 240px;
}
</style>
