const CURRENT_KEY = 'nutrisnap.current'
const LOCAL_HISTORY_KEY = 'nutrisnap.localHistory.v1'
const HIDDEN_HISTORY_KEY = 'nutrisnap.hiddenHistory.v1'

function readJson(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch {
    return fallback
  }
}

function writeJson(key, value, storage = window.localStorage) {
  try {
    storage.setItem(key, JSON.stringify(value))
    return true
  } catch {
    return false
  }
}

export function readCurrentResult() {
  try {
    return JSON.parse(window.sessionStorage.getItem(CURRENT_KEY) || 'null')
  } catch {
    return null
  }
}

export function writeCurrentResult(result) {
  try {
    window.sessionStorage.setItem(CURRENT_KEY, JSON.stringify(result))
  } catch {
    // Session storage can be disabled. The result remains usable in React state.
  }
}

function historySnapshot(result, inputType = 'paste') {
  const safeResult = { ...result }
  delete safeResult.detected_text
  return {
    id: `browser-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    created_at: new Date().toISOString(),
    score: safeResult.score,
    band: safeResult.band,
    source: inputType,
    result: safeResult,
    localOnly: true,
  }
}

export function saveLocalHistory(result, inputType = 'paste') {
  if (!result || result.status !== 'ok') return
  const current = readJson(LOCAL_HISTORY_KEY, [])
  const next = [historySnapshot(result, inputType), ...current].slice(0, 50)
  writeJson(LOCAL_HISTORY_KEY, next)
}

export function readLocalHistory() {
  const value = readJson(LOCAL_HISTORY_KEY, [])
  return Array.isArray(value) ? value : []
}

export function readHiddenHistoryIds() {
  const value = readJson(HIDDEN_HISTORY_KEY, [])
  return Array.isArray(value) ? value : []
}

export function hideHistoryIds(ids) {
  const next = [...new Set([...readHiddenHistoryIds(), ...ids])]
  writeJson(HIDDEN_HISTORY_KEY, next)
}

export function removeLocalHistoryIds(ids) {
  const hidden = new Set(ids)
  const next = readLocalHistory().filter((item) => !hidden.has(String(item.id)))
  writeJson(LOCAL_HISTORY_KEY, next)
}
