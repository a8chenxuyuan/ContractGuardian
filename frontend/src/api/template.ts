import request from './request'

export interface ContractTemplate {
  id: number
  name: string
  category: string
  scene: string | null
  content?: string
  is_preset: boolean
  usage_count: number
  created_at: string | null
}

export interface TemplateList {
  total: number
  items: ContractTemplate[]
}

export interface TemplateCategory {
  category: string
  count: number
}

export interface TemplateIn {
  name: string
  category: string
  scene?: string
  content: string
}

export function listTemplates(params: {
  skip?: number
  limit?: number
  keyword?: string
  category?: string
  mine?: boolean
}) {
  return request.get<TemplateList>('/templates', { params })
}

export function listTemplateCategories() {
  return request.get<TemplateCategory[]>('/templates/categories')
}

export function getTemplate(id: number) {
  return request.get<ContractTemplate>(`/templates/${id}`)
}

export function createTemplate(body: TemplateIn) {
  return request.post<ContractTemplate>('/templates', body)
}

export function deleteTemplate(id: number) {
  return request.delete(`/templates/${id}`)
}

export function downloadTemplate(id: number) {
  return request.get(`/templates/${id}/download`, { responseType: 'blob' })
}
