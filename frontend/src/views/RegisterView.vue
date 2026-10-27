<template>
  <div class="auth-page">
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

        <h1 class="hero-title">三分钟<br />完成一次专业审查</h1>
        <p class="hero-desc">
          上传合同后，AI 自动识别合同类型，多 Agent 并行审查，
          输出带法律依据与修改建议的可视化报告。
        </p>

        <ul class="hero-steps">
          <li v-for="(s, i) in steps" :key="s">
            <span class="step-index">{{ i + 1 }}</span>
            {{ s }}
          </li>
        </ul>

        <div class="hero-quote">
          “已覆盖劳动合同、租赁、服务、采购等 7 类合同，
          测试集合同级查全率与查准率均为 100%。”
        </div>
      </div>

      <!-- 右侧表单 -->
      <div class="form-side">
        <div class="form-box">
          <h2 class="form-title">创建账号</h2>
          <p class="form-sub">注册后即可免费体验完整审查流程</p>

          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-position="top"
            size="large"
            @submit.prevent="handleRegister"
          >
            <el-form-item label="邮箱" prop="email">
              <el-input v-model="form.email" type="email" placeholder="请输入邮箱">
                <template #prefix><el-icon><message /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-form-item label="昵称" prop="nickname">
              <el-input v-model="form.nickname" placeholder="请输入昵称（可选）">
                <template #prefix><el-icon><user /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="form.password"
                type="password"
                placeholder="至少 6 位密码"
                show-password
                @keyup.enter="handleRegister"
              >
                <template #prefix><el-icon><lock /></el-icon></template>
              </el-input>
            </el-form-item>

            <el-button
              class="submit-btn"
              type="primary"
              size="large"
              :loading="loading"
              @click="handleRegister"
            >
              注 册
            </el-button>
          </el-form>

          <p class="form-footer">
            已有账号？
            <router-link to="/login" class="link">立即登录</router-link>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, Message, User } from '@element-plus/icons-vue'
import { register } from '@/api/auth'

const router = useRouter()
const loading = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({ email: '', password: '', nickname: '' })

const rules: FormRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

const steps = [
  '上传 PDF / Word / 图片合同',
  'AI 自动解析并识别合同类型',
  '14 个 Agent 并行交叉审查',
  '查看报告、定位原文、导出归档',
]

async function handleRegister() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await register(form)
    ElMessage.success('注册成功，请登录')
    router.push('/login')
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
}

.hero-desc {
  margin-top: 14px;
  font-size: 13.5px;
  line-height: 1.8;
  opacity: 0.88;
  max-width: 420px;
}

.hero-steps {
  list-style: none;
  margin-top: 30px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.hero-steps li {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13.5px;
}

.step-index {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.16);
  font-size: 12px;
  font-weight: 600;
}

.hero-quote {
  margin-top: auto;
  padding-top: 28px;
  font-size: 12.5px;
  line-height: 1.8;
  opacity: 0.8;
}

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

.form-footer {
  margin-top: 22px;
  text-align: center;
  font-size: 13.5px;
  color: var(--cg-text-secondary);
}

.link {
  color: var(--cg-primary);
  font-weight: 600;
  text-decoration: none;
}

.link:hover {
  text-decoration: underline;
}

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
