<template>
  <el-drawer v-model="visible" size="420px" :append-to-body="true" class="ask-drawer">
    <template #header>
      <div class="drawer-head">
        <span class="drawer-title">条款追问</span>
        <span v-if="finding" class="ctx-badge" :class="finding.level">
          {{ levelText }} · {{ finding.risk_type }}
        </span>
      </div>
    </template>

    <div class="ask-body">
      <!-- 风险项上下文 -->
      <div class="ctx-box" v-if="finding">
        <p class="ctx-reason">{{ finding.reason }}</p>
        <p class="ctx-clause" v-if="finding.clause_text">{{ finding.clause_text }}</p>
      </div>

      <!-- 划词片段 -->
      <div class="snippet-chip" v-if="selectedSnippet">
        <span class="snippet-text">「{{ selectedSnippet }}」</span>
        <el-icon class="snippet-clear" title="清除划词" @click="selectedSnippet = ''"><close /></el-icon>
      </div>

      <div class="messages" ref="messagesRef">
        <div v-if="messages.length === 0" class="empty-tip">
          围绕该风险项继续提问，AI 将结合风险说明、法条依据与知识库检索结果作答。
        </div>
        <div v-for="(msg, i) in messages" :key="i" :class="['msg', msg.role]">
          <div class="bubble">{{ msg.content }}</div>
        </div>
        <div v-if="loading" class="msg assistant"><div class="bubble thinking">思考中...</div></div>
      </div>

      <div class="input-area">
        <el-input
          v-model="question"
          type="textarea"
          :rows="3"
          placeholder="针对该风险项输入追问..."
          @keydown.enter.prevent="send"
        />
        <el-button type="primary" :loading="loading" @click="send">发送</el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Close } from '@element-plus/icons-vue'
import { askAboutFinding } from '@/api/review'
import type { Finding } from '@/types'

const props = defineProps<{
  modelValue: boolean
  sessionId: number
  finding: Finding | null
  selectedText: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const question = ref('')
const loading = ref(false)
const messages = ref<{ role: 'user' | 'assistant'; content: string }[]>([])
const messagesRef = ref<HTMLDivElement>()
// 打开时从划词气泡带入的片段，可清除
const selectedSnippet = ref('')

const levelText = computed(() => {
  const map: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }
  return props.finding ? map[props.finding.level] || props.finding.level : ''
})

watch(visible, (v) => {
  if (v) {
    // 每次打开重置为新风险项的追问语境
    messages.value = []
    question.value = ''
    selectedSnippet.value = props.selectedText || ''
  }
})

async function send() {
  const q = question.value.trim()
  if (!q) {
    ElMessage.warning('请输入追问内容')
    return
  }
  if (!props.finding) {
    ElMessage.warning('缺少风险项上下文')
    return
  }

  messages.value.push({ role: 'user', content: q })
  question.value = ''
  loading.value = true
  scrollToBottom()

  try {
    const res = await askAboutFinding(
      props.sessionId,
      q,
      selectedSnippet.value || undefined,
      props.finding.id
    )
    messages.value.push({ role: 'assistant', content: res.answer })
    scrollToBottom()
  } catch {
    messages.value.push({ role: 'assistant', content: '追问失败，请稍后重试。' })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  })
}
</script>

<style scoped>
.drawer-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.drawer-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--cg-text);
}

.ctx-badge {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 20px;
}

.ctx-badge.high {
  color: #dc2626;
  background: #fef2f2;
}

.ctx-badge.medium {
  color: #d97706;
  background: #fffbeb;
}

.ctx-badge.low {
  color: #059669;
  background: #ecfdf5;
}

.ask-body {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.ctx-box {
  flex-shrink: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  margin-bottom: 10px;
}

.ctx-reason {
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--cg-text);
  margin: 0;
}

.ctx-clause {
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--cg-text-muted);
  margin: 6px 0 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.snippet-chip {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 8px;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  margin-bottom: 10px;
}

.snippet-text {
  flex: 1;
  font-size: 11.5px;
  line-height: 1.55;
  color: #3730a3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.snippet-clear {
  flex-shrink: 0;
  cursor: pointer;
  color: #818cf8;
  margin-top: 2px;
}

.snippet-clear:hover {
  color: #4f46e5;
}

.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0 12px;
}

.empty-tip {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--cg-text-muted);
  background: #f8fafc;
  border-radius: 10px;
  padding: 12px 14px;
}

.msg {
  display: flex;
}

.msg.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 88%;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg.user .bubble {
  background: var(--cg-primary);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.msg.assistant .bubble {
  background: #f1f5f9;
  color: var(--cg-text);
  border-bottom-left-radius: 4px;
}

.bubble.thinking {
  color: var(--cg-text-muted);
}

.input-area {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--cg-border);
}

.input-area .el-button {
  align-self: flex-end;
}
</style>
