<template>
  <div class="auth-page">
    <!-- 背景装饰 -->
    <div class="bg-blob blob-1"></div>
    <div class="bg-blob blob-2"></div>

    <div class="auth-panel">
      <!-- 左侧品牌区 -->
      <div class="hero-side">
        <div class="hero-brand">
          <div class="hero-logo">
            <el-icon :size="26"><lock /></el-icon>
          </div>
          <span class="hero-name">合同卫士</span>
        </div>

        <h1 class="hero-title">AI 驱动的<br />智能合同审查平台</h1>
        <p class="hero-desc">
          14 个专业 Agent 协作审查，覆盖权利义务、缺失条款、法律依据、
          交叉关联等维度，几分钟输出可溯源的专业审查报告。
        </p>

        <div class="hero-features">
          <div class="feature-item" v-for="f in features" :key="f.title">
            <div class="feature-icon">
              <el-icon :size="18"><component :is="f.icon" /></el-icon>
            </div>
            <div>
              <p class="feature-title">{{ f.title }}</p>
              <p class="feature-desc">{{ f.desc }}</p>
            </div>
          </div>
        </div>

        <div class="hero-stats">
          <div class="stat">
            <span class="stat-num">7</span>
            <span class="stat-label">合同类型</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat">
            <span class="stat-num">14</span>
            <span class="stat-label">审查 Agent</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat">
            <span class="stat-num">100%</span>
            <span class="stat-label">测试集召回</span>
          </div>
        </div>
      </div>

      <!-- 右侧表单区 -->
      <div class="form-side">
        <div class="form-box">
          <h2 class="form-title">欢迎回来</h2>
          <p class="form-sub">登录你的账号，继续守护合同安全</p>

          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-position="top"
            size="large"
            @submit.prevent="handleLogin"
          >
            <el-form-item label="邮箱" prop="email">
              <el-input v-model="form.email" type="email" placeholder="请输入邮箱">
                <template #prefix><el-icon><message /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="form.password"
                type="password"
                placeholder="请输入密码"
                show-password
                @keyup.enter="handleLogin"
              >
                <template #prefix><el-icon><lock /></el-icon></template>
              </el-input>
            </el-form-item>

            <el-button
              class="submit-btn"
              type="primary"
              size="large"
              :loading="loading"
              @click="handleLogin"
            >
              登 录
            </el-button>
          </el-form>

          <div class="form-footer-row">
            <a class="link forgot-link" @click="openForgot">忘记密码？</a>
            <p class="form-footer">
              还没有账号？
              <router-link to="/register" class="link">立即注册</router-link>
            </p>
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="forgotVisible" title="找回密码" width="420px" @closed="resetForgot">
      <el-steps :active="forgotStep" align-center finish-status="success" class="forgot-steps">
        <el-step title="验证邮箱" />
        <el-step title="重置密码" />
      </el-steps>

      <template v-if="forgotStep === 0">
        <p class="forgot-tip">输入注册邮箱，我们将发送 6 位验证码（10 分钟内有效）</p>
        <el-input
          v-model="forgot.email"
          type="email"
          size="large"
          placeholder="注册邮箱"
          :prefix-icon="Message"
        />
      </template>

      <template v-else-if="forgotStep === 1">
        <p class="forgot-tip">验证码已发送至 {{ forgot.email }}</p>
        <el-input
          v-model="forgot.code"
          size="large"
          maxlength="6"
          placeholder="6 位验证码"
          class="code-input"
        />
        <el-input
          v-model="forgot.newPassword"
          type="password"
          size="large"
          show-password
          placeholder="新密码（至少 6 位）"
          class="pwd-input"
          @keyup.enter="handleReset"
        />
      </template>

      <template v-else>
        <el-result icon="success" title="密码已重置" sub-title="请使用新密码登录账号" />
      </template>

      <template #footer>
        <el-button v-if="forgotStep < 2" @click="forgotVisible = false">取消</el-button>
        <el-button
          v-if="forgotStep === 0"
          type="primary"
          :loading="sending"
          @click="handleSendCode"
        >
          发送验证码
        </el-button>
        <el-button
          v-else-if="forgotStep === 1"
          type="primary"
          :loading="resetting"
          @click="handleReset"
        >
          重置密码
        </el-button>
        <el-button v-else type="primary" @click="forgotVisible = false">去登录</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import {
  Lock, Message, Cpu, Document, DataLine, ChatDotRound,
} from '@element-plus/icons-vue'
import { login, getMe, forgotPassword, resetPassword } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({ email: '', password: '' })

// 忘记密码流程状态
const forgotVisible = ref(false)
const forgotStep = ref(0) // 0 填邮箱 → 1 填验证码+新密码 → 2 成功
const sending = ref(false)
const resetting = ref(false)
const forgot = reactive({ email: '', code: '', newPassword: '' })

function openForgot() {
  forgotStep.value = 0
  forgotVisible.value = true
}

function resetForgot() {
  forgot.email = ''
  forgot.code = ''
  forgot.newPassword = ''
}

async function handleSendCode() {
  const email = forgot.email.trim()
  if (!/^\S+@\S+\.\S+$/.test(email)) {
    ElMessage.warning('请输入正确的邮箱地址')
    return
  }
  sending.value = true
  try {
    await forgotPassword(email)
    forgot.email = email
    forgotStep.value = 1
    ElMessage.success('验证码已发送，请查收邮件')
  } finally {
    sending.value = false
  }
}

async function handleReset() {
  if (forgot.code.trim().length !== 6) {
    ElMessage.warning('请输入 6 位验证码')
    return
  }
  if (forgot.newPassword.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  resetting.value = true
  try {
    await resetPassword({ email: forgot.email, code: forgot.code.trim(), new_password: forgot.newPassword })
    forgotStep.value = 2
  } finally {
    resetting.value = false
  }
}

const rules: FormRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const features = [
  { icon: Cpu, title: '多 Agent 协作审查', desc: '风险识别、法条验证、辩论仲裁全流程' },
  { icon: Document, title: '原文精准定位', desc: '风险条款与 PDF 原文双向高亮联动' },
  { icon: DataLine, title: '法条溯源可信', desc: '每条风险附带法律依据与置信度' },
  { icon: ChatDotRound, title: '对话式追问', desc: '选中文本即可向 AI 追问风险细节' },
]

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const res = await login(form)
    authStore.setToken(res.access_token)
    const user = await getMe()
    authStore.setUser(user)
    ElMessage.success('登录成功')
    router.push('/contracts')
  } catch (e) {
    // 错误由拦截器统一提示
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: var(--cg-bg);
}

/* 背景光斑 */
.bg-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.35;
  pointer-events: none;
}
.blob-1 {
  width: 480px;
  height: 480px;
  background: #c7d2fe;
  top: -120px;
  right: -80px;
  animation: float 9s ease-in-out infinite;
}
.blob-2 {
  width: 400px;
  height: 400px;
  background: #ddd6fe;
  bottom: -100px;
  left: -60px;
  animation: float 11s ease-in-out infinite reverse;
}
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-28px); }
}

/* 面板 */
.auth-panel {
  position: relative;
  display: flex;
  width: min(1080px, 94vw);
  min-height: 640px;
  border-radius: 24px;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.12);
}

/* 左侧品牌 */
.hero-side {
  flex: 1.15;
  padding: 48px 44px;
  background: var(--cg-gradient);
  color: #fff;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

.hero-side::after {
  content: '';
  position: absolute;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  border: 60px solid rgba(255, 255, 255, 0.07);
  right: -120px;
  bottom: -120px;
}

.hero-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hero-logo {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.16);
  backdrop-filter: blur(4px);
}

.hero-name {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 1px;
}

.hero-title {
  margin-top: 44px;
  font-size: 30px;
  line-height: 1.4;
  font-weight: 700;
  letter-spacing: -0.5px;
}

.hero-desc {
  margin-top: 14px;
  font-size: 13.5px;
  line-height: 1.8;
  opacity: 0.88;
  max-width: 420px;
}

.hero-features {
  margin-top: auto;
  padding-top: 28px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.feature-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.feature-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.15);
}

.feature-title {
  font-size: 13px;
  font-weight: 600;
}

.feature-desc {
  font-size: 11.5px;
  opacity: 0.78;
  margin-top: 2px;
}

.hero-stats {
  margin-top: 26px;
  display: flex;
  align-items: center;
  gap: 18px;
}

.stat {
  display: flex;
  flex-direction: column;
}

.stat-num {
  font-size: 22px;
  font-weight: 700;
}

.stat-label {
  font-size: 11px;
  opacity: 0.75;
}

.stat-divider {
  width: 1px;
  height: 28px;
  background: rgba(255, 255, 255, 0.25);
}

/* 右侧表单 */
.form-side {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.form-box {
  width: 100%;
  max-width: 360px;
}

.form-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--cg-text);
}

.form-sub {
  margin: 6px 0 28px;
  font-size: 13px;
  color: var(--cg-text-muted);
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  height: 44px;
  font-size: 15px;
  letter-spacing: 4px;
  border-radius: 10px;
}

.form-footer-row {
  margin-top: 22px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.forgot-link {
  font-size: 13.5px;
  cursor: pointer;
}

.form-footer {
  margin: 0;
  text-align: right;
  font-size: 13.5px;
  color: var(--cg-text-secondary);
}

.forgot-steps {
  margin-bottom: 20px;
}

.forgot-tip {
  font-size: 13px;
  color: var(--cg-text-secondary);
  margin-bottom: 12px;
}

.code-input,
.pwd-input {
  margin-bottom: 12px;
}

.link {
  color: var(--cg-primary);
  font-weight: 600;
  text-decoration: none;
}

.link:hover {
  text-decoration: underline;
}

/* 窄屏适配 */
@media (max-width: 860px) {
  .hero-side {
    display: none;
  }
  .auth-panel {
    min-height: auto;
  }
  .form-side {
    padding: 44px 28px;
  }
}
</style>
