<template>
  <div class="kb-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">法规知识库</h2>
        <p class="page-sub">审查引擎引用的法条依据都在这里，支持关键词与分类检索</p>
      </div>
    </div>

    <div class="cg-card toolbar">
      <el-input
        v-model="keyword"
        class="search-input"
        placeholder="搜索法名、条号或条文内容，回车检索"
        clearable
        :prefix-icon="Search"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <div class="cat-chips">
        <span
          class="cat-chip"
          :class="{ active: activeCategory === '' }"
          @click="onCategory('')"
        >
          全部
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

    <div class="cg-card list-card">
      <div v-if="loading" class="empty-tip">加载中…</div>
      <div v-else-if="!items.length" class="empty-tip">没有匹配的法规条目，换个关键词试试</div>
      <div v-for="item in items" :key="item.id" class="law-row">
        <div class="law-head" @click="toggle(item.id)">
          <span class="law-name">{{ item.law_name }}</span>
          <span class="law-number">{{ item.article_number }}</span>
          <el-tag size="small" effect="plain" round class="law-cat">{{ item.category }}</el-tag>
          <el-icon class="expand-icon" :class="{ open: expanded.has(item.id) }"><arrow-down /></el-icon>
        </div>
        <p v-if="item.article_title" class="law-title">{{ item.article_title }}</p>
        <p class="law-text" :class="{ clamped: !expanded.has(item.id) }">{{ item.article_text }}</p>
        <a
          v-if="item.metadata_json?.source_url"
          class="law-source"
          :href="item.metadata_json.source_url"
          target="_blank"
          rel="noopener"
          @click.stop
        >
          来源链接
        </a>
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowDown, Search } from '@element-plus/icons-vue'
import { listKnowledgeArticles, listKnowledgeCategories } from '@/api/knowledge'
import type { KnowledgeArticle, KnowledgeCategory } from '@/api/knowledge'

const items = ref<KnowledgeArticle[]>([])
const categories = ref<KnowledgeCategory[]>([])
const total = ref(0)
const keyword = ref('')
const activeCategory = ref('')
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const expanded = ref(new Set<number>())

async function load() {
  loading.value = true
  try {
    const res = await listKnowledgeArticles({
      skip: (page.value - 1) * pageSize,
      limit: pageSize,
      keyword: keyword.value || undefined,
      category: activeCategory.value || undefined,
    })
    items.value = res.items
    total.value = res.total
    // 翻页/换筛选后收起全部展开状态
    expanded.value = new Set()
  } finally {
    loading.value = false
  }
}

async function loadCategories() {
  categories.value = await listKnowledgeCategories()
}

function onSearch() {
  page.value = 1
  load()
}

function onCategory(category: string) {
  activeCategory.value = category
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function toggle(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  expanded.value = next
}

onMounted(() => {
  loadCategories()
  load()
})
</script>

<style scoped>
.kb-page {
  max-width: 880px;
  margin: 0 auto;
}

.page-head {
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

.list-card {
  padding: 8px 20px 16px;
}

.empty-tip {
  color: var(--cg-text-muted);
  font-size: 13px;
  text-align: center;
  padding: 56px 0;
}

.law-row {
  padding: 16px 4px;
  border-bottom: 1px solid #f1f5f9;
}

.law-row:last-of-type {
  border-bottom: none;
}

.law-head {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.law-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--cg-text);
}

.law-number {
  font-size: 13px;
  color: var(--cg-primary);
  font-weight: 600;
}

.law-cat {
  color: var(--cg-text-muted);
}

.expand-icon {
  margin-left: auto;
  color: var(--cg-text-muted);
  transition: transform 0.2s;
}

.expand-icon.open {
  transform: rotate(180deg);
}

.law-title {
  font-size: 13px;
  color: var(--cg-text-secondary);
  margin-top: 6px;
}

.law-text {
  font-size: 13px;
  color: var(--cg-text-secondary);
  line-height: 1.7;
  margin-top: 8px;
  white-space: pre-wrap;
}

.law-text.clamped {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.law-source {
  display: inline-block;
  font-size: 12px;
  color: var(--cg-primary);
  margin-top: 6px;
}

.pager {
  display: flex;
  justify-content: center;
  padding-top: 14px;
}
</style>
