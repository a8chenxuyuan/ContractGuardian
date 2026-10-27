import request from './request'

export interface KnowledgeArticle {
  id: number
  law_name: string
  article_number: string
  article_title: string | null
  article_text: string
  category: string
  effective_date: string | null
  metadata_json: { source?: string; source_url?: string } | null
  created_at: string
}

export interface KnowledgeArticleList {
  total: number
  items: KnowledgeArticle[]
}

export interface KnowledgeCategory {
  category: string
  count: number
}

export function listKnowledgeArticles(params: {
  skip?: number
  limit?: number
  keyword?: string
  category?: string
}) {
  return request.get<KnowledgeArticleList>('/knowledge/articles', { params })
}

export function listKnowledgeCategories() {
  return request.get<KnowledgeCategory[]>('/knowledge/categories')
}
