<template>
  <div class="pdf-viewer">
    <div class="toolbar">
      <div class="toolbar-left">
        <span class="file-chip" :class="'chip-' + fileType">
          <el-icon :size="12"><document /></el-icon>
          {{ fileTypeLabel }}
        </span>
        <template v-if="fileType === 'pdf'">
          <el-divider direction="vertical" />
          <el-button size="small" text :disabled="page <= 1" @click="prevPage">
            <el-icon><arrow-left /></el-icon>
          </el-button>
          <span class="page-indicator">{{ page }} / {{ totalPages }}</span>
          <el-button size="small" text :disabled="page >= totalPages" @click="nextPage">
            <el-icon><arrow-right /></el-icon>
          </el-button>
        </template>
      </div>
      <el-button size="small" text type="primary" @click="loadDocument">
        <el-icon><refresh /></el-icon> 重新加载
      </el-button>
    </div>

    <div class="doc-scroll" ref="containerRef">
      <canvas v-if="fileType === 'pdf'" ref="canvasRef" class="pdf-canvas"></canvas>
      <div
        v-else-if="fileType === 'docx'"
        ref="docxRef"
        class="docx-paper"
        v-html="docxHtml"
      ></div>
      <div v-else-if="fileType === 'image'" class="image-paper">
        <img v-if="imageUrl" :src="imageUrl" alt="合同图片预览" />
        <p v-else class="image-loading">正在加载合同图片...</p>
      </div>
      <div v-else class="unsupported-tip">
        <p v-if="loadingFile">正在获取合同文件信息...</p>
        <template v-else>
          <p>文档加载中，当前文件为 <strong>{{ fileTypeLabel }}</strong> 格式。</p>
          <p v-if="contractId">
            您可以
            <el-link type="primary" @click="downloadFile">下载原文件</el-link>
            查看，或通过右侧“导出 Word”生成审查报告。
          </p>
        </template>
      </div>
    </div>

    <p class="hint">
      <el-icon :size="13"><info-filled /></el-icon>
      点击风险卡片的“定位原文”可跳转到文档对应位置并高亮显示
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import mammoth from 'mammoth'
import { ElMessage } from 'element-plus'
import {
  Document, ArrowLeft, ArrowRight, Refresh, InfoFilled,
} from '@element-plus/icons-vue'
import { getContract, downloadContractFile } from '@/api/contracts'
import { useAuthStore } from '@/stores/auth'
import type { Finding } from '@/types'

// 使用 CDN 版本的 pdf.js worker
// 生产环境建议把 worker 文件放到 public 目录，避免依赖外部 CDN
pdfjsLib.GlobalWorkerOptions.workerSrc =
  'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.1.392/pdf.worker.min.js'

interface Bbox {
  x: number
  y: number
  w: number
  h: number
}

const props = defineProps<{
  contractId: number
  findings: Finding[]
  highlightPage?: number
  highlightBbox?: Bbox | null
}>()

const emit = defineEmits<{
  (e: 'selectText', text: string): void
}>()

const containerRef = ref<HTMLDivElement>()
const canvasRef = ref<HTMLCanvasElement>()
const docxRef = ref<HTMLDivElement>()
const page = ref(1)
const totalPages = ref(1)
let pdfDoc: any = null
const scale = 1.5
const fileUrl = ref<string | null>(null)
const fileType = ref<string>('')
const loadingFile = ref(false)
const docxHtml = ref<string>('')
const imageUrl = ref<string>('')
const fileTypeLabel = computed(() => fileType.value.toUpperCase() || '未知')

async function loadContractInfo() {
  loadingFile.value = true
  try {
    const contract = await getContract(props.contractId)
    fileType.value = (contract.file_type || '').toLowerCase()
    fileUrl.value = contract.file_url || null
  } catch (e: any) {
    ElMessage.error('获取合同信息失败：' + (e.message || '未知错误'))
  } finally {
    loadingFile.value = false
  }
}

function getFullUrl(url: string | null): string | null {
  if (!url) return null
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  // 相对路径补全为当前站点绝对地址
  const base = window.location.origin
  return base + (url.startsWith('/') ? url : '/' + url)
}

/** 带 token 的请求头（合同文件接口需要鉴权） */
function authHeaders(): Record<string, string> {
  const authStore = useAuthStore()
  return authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}
}

/** 触发浏览器下载合同原文件 */
async function downloadFile() {
  try {
    const blob = await downloadContractFile(props.contractId)
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', 'contract')
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('下载失败，请稍后重试')
  }
}

async function loadDocument(silent = false) {
  if (!fileType.value) {
    await loadContractInfo()
  }

  if (!fileUrl.value) {
    ElMessage.warning('未找到合同文件地址')
    return
  }

  const fullUrl = getFullUrl(fileUrl.value)
  if (!fullUrl) return

  if (fileType.value === 'pdf') {
    await loadPdf(fullUrl, silent)
  } else if (fileType.value === 'docx') {
    await loadDocx(fullUrl, silent)
  } else if (fileType.value === 'image') {
    await loadImage(silent)
  } else {
    ElMessage.warning(`当前文件为 ${fileTypeLabel.value} 格式，文档加载失败，可下载原文件查看`)
  }
}

async function loadPdf(url: string, silent = false) {
  try {
    // pdf.js 支持 httpHeaders，为受鉴权的文件接口携带 token
    pdfDoc = await pdfjsLib.getDocument({
      url,
      httpHeaders: authHeaders(),
      withCredentials: false,
    }).promise
    totalPages.value = pdfDoc.numPages
    renderPage(page.value)
    if (!silent) ElMessage.success('PDF 加载成功')
  } catch (e: any) {
    ElMessage.error('PDF 加载失败：' + (e.message || '未知错误'))
    console.warn('PDF 加载失败', e)
  }
}

async function loadDocx(url: string, silent = false) {
  try {
    const response = await fetch(url, { headers: authHeaders() })
    if (!response.ok) {
      throw new Error(`下载失败：${response.status} ${response.statusText}`)
    }
    const arrayBuffer = await response.arrayBuffer()
    const result = await mammoth.convertToHtml({ arrayBuffer })
    docxHtml.value = result.value
    if (result.messages.length) {
      console.warn('DOCX 转换提示', result.messages)
    }
    if (!silent) ElMessage.success('Word 文档加载成功')
    bindDocxTextSelection()
  } catch (e: any) {
    ElMessage.error('Word 文档加载失败：' + (e.message || '未知错误'))
    console.warn('Word 文档加载失败', e)
  }
}

async function loadImage(silent = false) {
  try {
    // img 标签无法携带 Authorization 头，走鉴权接口取 blob 再本地展示
    const blob = await downloadContractFile(props.contractId)
    if (imageUrl.value) window.URL.revokeObjectURL(imageUrl.value)
    imageUrl.value = window.URL.createObjectURL(blob)
    if (!silent) ElMessage.success('图片加载成功')
  } catch (e: any) {
    ElMessage.error('图片加载失败：' + (e.message || '未知错误'))
    console.warn('图片加载失败', e)
  }
}

function bindDocxTextSelection() {
  // 延迟绑定，等待 DOM 渲染
  setTimeout(() => {
    const el = docxRef.value
    if (!el) return
    el.addEventListener('mouseup', () => {
      const selection = window.getSelection()
      const text = selection?.toString().trim() || ''
      if (text) {
        emit('selectText', text)
      }
    })
  }, 0)
}

async function renderPage(num: number) {
  if (!pdfDoc || !canvasRef.value) return
  const canvas = canvasRef.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const pdfPage = await pdfDoc.getPage(num)
  const viewport = pdfPage.getViewport({ scale })
  canvas.width = viewport.width
  canvas.height = viewport.height

  // 清空画布
  ctx.clearRect(0, 0, canvas.width, canvas.height)

  await pdfPage.render({ canvasContext: ctx, viewport }).promise

  // 如果当前页需要高亮，绘制高亮框
  if (num === props.highlightPage && props.highlightBbox) {
    drawHighlight(ctx, viewport, props.highlightBbox)
  }
}

function drawHighlight(
  ctx: CanvasRenderingContext2D,
  viewport: any,
  bbox: Bbox
) {
  // 把 PDF 坐标转换为 viewport 坐标
  // PDF 原点在左下角，viewport 原点在左上角，需要转换
  const x1 = bbox.x
  const y1 = bbox.y
  const x2 = bbox.x + bbox.w
  const y2 = bbox.y + bbox.h

  const topLeft = viewport.convertToViewportPoint(x1, y2)
  const bottomRight = viewport.convertToViewportPoint(x2, y1)

  const vx = topLeft[0]
  const vy = topLeft[1]
  const vw = bottomRight[0] - topLeft[0]
  const vh = bottomRight[1] - topLeft[1]

  ctx.save()
  ctx.fillStyle = 'rgba(255, 215, 0, 0.3)'
  ctx.strokeStyle = 'rgba(255, 140, 0, 0.8)'
  ctx.lineWidth = 2
  ctx.fillRect(vx, vy, vw, vh)
  ctx.strokeRect(vx, vy, vw, vh)
  ctx.restore()
}

function prevPage() {
  if (page.value > 1) {
    page.value--
    renderPage(page.value)
  }
}

function nextPage() {
  if (page.value < totalPages.value) {
    page.value++
    renderPage(page.value)
  }
}

// 监听高亮位置变化，自动跳转并渲染
watch(
  () => [props.highlightPage, props.highlightBbox],
  () => {
    if (!props.highlightPage || !props.highlightBbox) return
    if (!pdfDoc) return

    page.value = props.highlightPage
    renderPage(page.value)

    // 滚动到 PDF 可视区域
    containerRef.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  },
  { immediate: true }
)

onMounted(async () => {
  // 自动获取合同文件信息并加载预览（图片/Word/PDF 首屏即出，无需手动点重新加载）
  await loadContractInfo()
  if (fileType.value && fileUrl.value) {
    await loadDocument()
  }
})
</script>

<style scoped>
.pdf-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* ---------- 顶部工具栏 ---------- */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: #fbfcfe;
  border-bottom: 1px solid var(--cg-border);
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 4px 10px;
  border-radius: 20px;
}

.chip-pdf {
  color: #dc2626;
  background: #fee2e2;
}

.chip-docx, .chip-doc {
  color: #2563eb;
  background: #dbeafe;
}

.chip-png, .chip-jpg, .chip-jpeg, .chip-image {
  color: #7c3aed;
  background: #ede9fe;
}

.page-indicator {
  font-size: 12.5px;
  color: var(--cg-text-secondary);
  font-variant-numeric: tabular-nums;
  min-width: 52px;
  text-align: center;
}

/* ---------- 文档滚动区 ---------- */
.doc-scroll {
  flex: 1;
  overflow: auto;
  padding: 28px 28px 40px;
  background: var(--cg-bg);
}

/* PDF 画布：模拟纸张 */
.pdf-canvas {
  display: block;
  margin: 0 auto;
  background: #fff;
  border-radius: 10px;
  box-shadow: var(--cg-shadow);
  max-width: 100%;
}

/* Word 预览：纸张卡片 */
.docx-paper {
  background: #fff;
  max-width: 820px;
  min-width: 0;
  margin: 0 auto;
  padding: 52px 60px;
  border-radius: 12px;
  border: 1px solid var(--cg-border);
  box-shadow: var(--cg-shadow-sm);
  font-size: 14.5px;
  line-height: 2;
  color: #334155;
  overflow-wrap: break-word;
  word-wrap: break-word;
}

.docx-paper :deep(p) {
  margin: 0.9em 0;
  text-align: justify;
}

/* 条款标题（加粗行）层次 */
.docx-paper :deep(strong) {
  font-weight: 600;
  color: #1e293b;
}

.docx-paper :deep(h1),
.docx-paper :deep(h2),
.docx-paper :deep(h3) {
  font-size: 15.5px;
  font-weight: 700;
  color: #1e293b;
  margin: 1.4em 0 0.6em;
  padding-left: 10px;
  border-left: 3px solid var(--cg-primary);
}

/* 落款/日期右对齐常见样式保持默认 */
.docx-paper :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 1.2em 0;
  font-size: 13.5px;
}

.docx-paper :deep(td),
.docx-paper :deep(th) {
  border: 1px solid #e2e8f0;
  padding: 8px 10px;
}

.docx-paper :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}

.docx-paper :deep(ul),
.docx-paper :deep(ol) {
  margin: 0.8em 0;
  padding-left: 2em;
}

.docx-paper :deep(li) {
  margin: 0.35em 0;
}

/* 图片预览：纸张卡片，同 docx-paper 视觉层次 */
.image-paper {
  background: #fff;
  max-width: 860px;
  margin: 0 auto;
  padding: 16px;
  border-radius: 12px;
  border: 1px solid var(--cg-border);
  box-shadow: var(--cg-shadow-sm);
}

.image-paper img {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 6px;
}

.image-loading {
  padding: 60px 0;
  text-align: center;
  color: var(--cg-text-muted);
  font-size: 14px;
}

/* ---------- 底部提示 ---------- */
.hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px;
  font-size: 12px;
  color: var(--cg-text-muted);
  background: #fbfcfe;
  border-top: 1px solid var(--cg-border);
  flex-shrink: 0;
}

/* ---------- 未支持格式 ---------- */
.unsupported-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--cg-text-muted);
  font-size: 14px;
  text-align: center;
  padding: 40px;
}

.unsupported-tip p {
  margin: 8px 0;
}
</style>
