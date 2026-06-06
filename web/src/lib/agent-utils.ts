export const isJsonBlocks = (content: string) => {
  if (!content) return false
  const trimmed = content.trim()
  if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) return false
  try {
    const parsed = JSON.parse(trimmed)
    return Array.isArray(parsed) && parsed.length > 0 && parsed.every(block => typeof block === 'object' && block !== null)
  } catch {
    return false
  }
}

export const parseJsonBlocks = (content: string) => {
  try {
    return JSON.parse(content.trim())
  } catch {
    return []
  }
}
