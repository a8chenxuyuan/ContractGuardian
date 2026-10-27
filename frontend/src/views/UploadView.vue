<template>
  <div class="upload-page">
    <div class="page-header">
      <h2>上传合同</h2>
      <p>支持 PDF / Word / 图片，AI 自动识别 7 大合同类型并开始审查</p>
    </div>

    <!-- 流程步骤 -->
    <el-steps :active="stepActive" align-center class="flow-steps">
      <el-step title="上传合同" description="PDF / Word / 图片" />
      <el-step title="AI 解析" description="提取条款 · 识别类型" />
      <el-step title="多 Agent 审查" description="14 个维度并行" />
      <el-step title="查看报告" description="风险定位 · 导出归档" />
    </el-steps>

    <div class="upload-grid">
      <!-- 左：上传区 -->
      <div class="upload-panel cg-card">
        <el-upload
          drag
          action="#"
          :auto-upload="false"
          :show-file-list="false"
          :on-change="handleFileChange"
          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg"
        >
          <div class="dropzone-inner">
            <div class="dropzone-icon">
              <el-icon :size="34"><upload-filled /></el-icon>
            </div>
            <p class="dropzone-main">
              拖拽文件到此处，或 <em>点击选择文件</em>
            </p>
            <p class="dropzone-sub">单个文件不超过 20MB</p>
          </div>
        </el-upload>

        <!-- 已选文件 -->
        <transition name="page-fade">
          <div v-if="selectedFile" class="selected-file">
            <div class="file-info">
              <div class="file-icon">
                <el-icon :size="18"><document /></el-icon>
              </div>
              <div class="file-meta">
                <span class="file-name">{{ selectedFile.name }}</span>
                <span class="file-size">{{ formatSize(selectedFile.size) }}</span>
              </div>
            </div>
            <div class="file-actions">
              <el-button text type="danger" @click="clearFile">
                <el-icon><delete /></el-icon> 移除
              </el-button>
              <el-button type="primary" round :loading="uploading" @click="handleUpload">
                上传并解析
              </el-button>
            </div>
          </div>
        </transition>

        <el-alert
          v-if="error"
          :title="error"
          type="error"
          show-icon
          :closable="false"
          class="upload-error"
        />
      </div>

      <!-- 右：说明面板 -->
      <div class="info-panel">
        <div class="info-card cg-card">
          <h4><el-icon><circle-check /></el-icon> 支持的合同类型</h4>
          <div class="type-tags">
            <el-tag v-for="t in contractTypes" :key="t" effect="plain" round>{{ t }}</el-tag>
          </div>
        </div>

        <div class="info-card cg-card">
          <h4><el-icon><magic-stick /></el-icon> 审查维度</h4>
          <ul class="dim-list">
            <li v-for="d in dimensions" :key="d">{{ d }}</li>
          </ul>
        </div>

        <div class="info-card tip-card">
          <h4><el-icon><info-filled /></el-icon> 温馨提示</h4>
          <p>图片合同将进行 OCR 识别；扫描版 PDF 建议先转为 Word 以获得更准确的解析结果。</p>
        </div>
      </div>
    </div>

    <PaywallDialog
      v-model="paywallVisible"
      :reason="paywallReason"
      :used="paywallUsed"
      :limit="paywallLimit"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  UploadFilled, Document, Delete, CircleCheck, MagicStick, InfoFilled,
} from '@element-plus/icons-vue'
import { uploadContract } from '@/api/contracts'
import PaywallDialog from '@/components/PaywallDialog.vue'

const router = useRouter()
const selectedFile = ref<File | null>(null)
const uploading = ref(false)
const error = ref('')

const stepActive = computed(() => (selectedFile.value ? 1 : 0))

const contractTypes = [
  '劳动合同', '房屋租赁', '服务合同', '采购合同',
  '销售合同', '保密协议', '合作协议',
]

const dimensions = [
  '风险识别 · 红线条款快检',
  '缺失条款检测 · 权利义务对等',
  '法律依据溯源 · 法条交叉验证',
  '跨条款关联 · 正反辩论仲裁',
]

const MAX_SIZE = 20 * 1024 * 1024
const ACCEPT = ['.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg']

function handleFileChange(file: any) {
  error.value = ''
  const raw: File = file.raw
  const ext = '.' + (raw.name.split('.').pop() || '').toLowerCase()
  if (!ACCEPT.includes(ext)) {
    error.value = `不支持的文件格式 ${ext}，请上传 PDF / Word / 图片`
    return
  }
  if (raw.size > MAX_SIZE) {
    error.value = '文件超过 20MB 限制，请压缩后重试'
    return
  }
  selectedFile.value = raw
}

function clearFile() {
  selectedFile.value = null
  error.value = ''
}

function formatSize(bytes: number) {
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

async function handleUpload() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择文件')
    return
  }
  uploading.value = true
  try {
    await uploadContract(selectedFile.value)
    ElMessage.success('上传成功，正在后台解析')
    router.push('/contracts')
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    if (err?.response?.status === 402 && detail?.code === 'QUOTA_EXCEEDED') {
      paywallReason.value = detail.reason
      paywallUsed.value = detail.used
      paywallLimit.value = detail.limit
      paywallVisible.value = true
    }
  } finally {
    uploading.value = false
  }
}

// ---------- 配额不足升级引导 ----------
const paywallVisible = ref(false)
const paywallReason = ref<'monthly_reviews' | 'page_limit'>('page_limit')
const paywallUsed = ref<number>()
const paywallLimit = ref<number>()
</script>

<style scoped>
.upload-page {
  max-width: 1080px;
  margin: 0 auto;
}

/* 步骤条 */
.flow-steps {
  background: #fff;
  border: 1px solid var(--cg-border);
  border-radius: var(--cg-radius);
  padding: 22px 16px 14px;
  margin-bottom: 22px;
}

.upload-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 18px;
  align-items: start;
}

/* 上传卡片 */
.upload-panel {
  padding: 14px;
}

.upload-panel :deep(.el-upload-dragger) {
  border: 2px dashed #c7d2fe;
  border-radius: 14px;
  background: linear-gradient(180deg, #fafaff 0%, #f5f3ff 100%);
  transition: all 0.25s ease;
  padding: 40px 20px;
}

.upload-panel :deep(.el-upload-dragger:hover) {
  border-color: var(--cg-primary);
  box-shadow: 0 8px 24px rgba(79, 70, 229, 0.12);
}

.dropzone-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  pointer-events: none;
}

.dropzone-icon {
  width: 64px;
  height: 64px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--cg-gradient);
  color: #fff;
  margin-bottom: 8px;
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.3);
}

.dropzone-main {
  font-size: 14.5px;
  color: var(--cg-text-secondary);
}

.dropzone-main em {
  color: var(--cg-primary);
  font-style: normal;
  font-weight: 600;
}

.dropzone-sub {
  font-size: 12px;
  color: var(--cg-text-muted);
}

/* 已选文件 */
.selected-file {
  margin-top: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px;
  border-radius: 12px;
  background: var(--cg-gradient-soft);
  border: 1px solid #e0e7ff;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.file-icon {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--cg-gradient);
  color: #fff;
}

.file-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.file-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--cg-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}

.file-size {
  font-size: 12px;
  color: var(--cg-text-muted);
}

.file-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.upload-error {
  margin-top: 14px;
}

/* 右侧说明 */
.info-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.info-card {
  padding: 18px;
}

.info-card h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--cg-text);
  margin-bottom: 12px;
}

.info-card h4 .el-icon {
  color: var(--cg-primary);
}

.type-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.dim-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dim-list li {
  font-size: 13px;
  color: var(--cg-text-secondary);
  padding-left: 14px;
  position: relative;
}

.dim-list li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 7px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--cg-gradient);
}

.tip-card {
  background: #fffbeb;
  border-color: #fde68a;
}

.tip-card h4 {
  color: #92400e;
}

.tip-card h4 .el-icon {
  color: #f59e0b;
}

.tip-card p {
  font-size: 12.5px;
  line-height: 1.7;
  color: #a16207;
}

@media (max-width: 900px) {
  .upload-grid {
    grid-template-columns: 1fr;
  }
}
</style>
