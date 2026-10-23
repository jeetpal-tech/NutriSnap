const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export class ApiError extends Error {
  constructor(message, status = 0, data = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

function messageFromResponse(data, fallback) {
  if (typeof data?.message === 'string' && data.message.trim()) return data.message
  if (typeof data?.detail === 'string' && data.detail.trim()) return data.detail
  if (Array.isArray(data?.detail)) {
    const message = data.detail.find((item) => typeof item?.msg === 'string')?.msg
    if (message) return message
  }
  return fallback
}

export async function requestJson(path, options = {}) {
  const { signal, ...fetchOptions } = options
  let response
  try {
    response = await fetch(`${API}${path}`, { ...fetchOptions, signal })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ApiError('NutriSnap could not reach the service. Check your connection and try again.')
  }

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new ApiError(messageFromResponse(data, 'That request could not be completed.'), response.status, data)
  }
  return data
}

export function analyzeIngredients(ingredientsText, { signal, profile, forceMode = 'auto' } = {}) {
  return requestJson('/api/analyze', {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ ingredients_text: ingredientsText, profile, force_mode: forceMode }),
  })
}

export function scanLabelImage(file, { signal } = {}) {
  const body = new FormData()
  body.append('file', file)
  return requestJson('/api/scan-image', { method: 'POST', signal, body })
}

export function loadHistory({ signal } = {}) {
  return requestJson('/api/history?limit=100', { signal, headers: { Accept: 'application/json' } })
}
