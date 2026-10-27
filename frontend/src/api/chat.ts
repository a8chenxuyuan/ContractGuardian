import request from './request'

export function sendChat(contractId: number, question: string, selectedText?: string) {
  return request.post<{ answer: string; references: any[] }>(
    `/contracts/${contractId}/chat`,
    {
      question,
      selected_text: selectedText,
    }
  )
}

export function getChatHistory(contractId: number) {
  return request.get<any[]>(`/contracts/${contractId}/chat/history`)
}
