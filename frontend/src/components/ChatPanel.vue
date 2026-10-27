<template>
  <div class="chat-panel">
    <h4>划词追问</h4>
    <div class="selected-text" v-if="selectedText">
      <strong>已选：</strong>{{ selectedText }}
      <el-button size="small" link @click="clearSelected">清除</el-button>
    </div>

    <div class="messages" ref="messagesRef">
      <div
        v-for="(msg, index) in messages"
        :key="index"
        :class="['message', msg.role]"
      >
        <div class="bubble">{{ msg.content }}</div>
      </div>
    </div>

    <div class="input-area">
      <el-input
        v-model="question"
        type="textarea"
        :rows="2"
        placeholder="输入您的问题..."
        @keydown.enter.prevent="send"
      />
      <el-button type="primary" :loading="loading" @click="send">发送</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { sendChat } from '@/api/chat'

const props = defineProps<{
  contractId: number
  selectedText: string
}>()

const emit = defineEmits<{
  (e: 'clearSelected'): void
}>()

const question = ref('')
const loading = ref(false)
const messages = ref<{ role: 'user' | 'assistant'; content: string }[]>([])
const messagesRef = ref<HTMLDivElement>()

function clearSelected() {
  // selectedText 是父组件状态，通知父组件清空；输入框预填与消息流一并重置
  emit('clearSelected')
  question.value = ''
  messages.value = []
}

async function send() {
  const q = question.value.trim()
  if (!q) {
    ElMessage.warning('请输入问题')
    return
  }

  messages.value.push({ role: 'user', content: q })
  question.value = ''
  loading.value = true
  scrollToBottom()

  try {
    const res = await sendChat(props.contractId, q, props.selectedText || undefined)
    messages.value.push({ role: 'assistant', content: res.answer })
    scrollToBottom()
  } finally {
    loading.value = false
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

watch(
  () => props.selectedText,
  (text) => {
    if (text) {
      question.value = `请帮我看看这段内容是否有问题：${text}`
    }
  }
)
</script>

<style scoped>
.chat-panel {
  margin-top: 24px;
  padding: 16px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
}

.selected-text {
  margin-bottom: 12px;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.messages {
  max-height: 300px;
  overflow-y: auto;
  margin-bottom: 12px;
}

.message {
  margin-bottom: 12px;
}

.message.user {
  text-align: right;
}

.bubble {
  display: inline-block;
  padding: 8px 12px;
  border-radius: 8px;
  background: #f5f7fa;
  color: #303133;
  max-width: 80%;
  text-align: left;
}

.message.user .bubble {
  background: #409eff;
  color: #fff;
}

.input-area {
  display: flex;
  gap: 8px;
}
</style>
