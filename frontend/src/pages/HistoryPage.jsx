import React from 'react'
import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Camera, ClipboardPaste, Clock3, Search, Trash2, Upload, X } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, Button, Card, EmptyState, PageIntro, Spinner } from '../components/ui.jsx'
import { loadHistory } from '../lib/api.js'
import { hideHistoryIds, readHiddenHistoryIds, readLocalHistory, removeLocalHistoryIds, writeCurrentResult } from '../lib/storage.js'

function titleFor(item) {
  const first = item.result?.ingredients?.find((ingredient) => ingredient.canonical || ingredient.name)
  return first?.canonical || first?.name || (item.source === 'camera' || item.source === 'upload' ? 'Label photo check' : 'Pasted ingredient check')
}

function dateFor(item) {
  const value = item.created_at || item.createdAt
  if (!value) return 'Date unavailable'
  try { return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) } catch { return value }
}

function sourceLabel(source) {
  if (source === 'camera') return { label: 'Camera', icon: <Camera size={16}/> }
  if (source === 'upload') return { label: 'Photo upload', icon: <Upload size={16}/> }
  return { label: 'Pasted text', icon: <ClipboardPaste size={16}/> }
}

function mergeItems(serverItems, localItems, hiddenIds) {
  const hidden = new Set(hiddenIds.map(String))
  const byKey = new Map()
  ;[...serverItems, ...localItems].forEach((item) => {
    if (!item?.id || hidden.has(String(item.id))) return
    const key = item.result?.created_at || `${item.score}-${item.created_at}`
    if (!byKey.has(key)) byKey.set(key, item)
  })
  return [...byKey.values()].sort((a, b) => new Date(b.created_at || b.createdAt || 0) - new Date(a.created_at || a.createdAt || 0))
}

export default function HistoryPage() {
  const navigate = useNavigate()
  const [serverItems, setServerItems] = useState([])
  const [localItems, setLocalItems] = useState(readLocalHistory)
  const [hiddenIds, setHiddenIds] = useState(readHiddenHistoryIds)
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [confirmClear, setConfirmClear] = useState(false)
  const pageSize = 7

  useEffect(() => {
    const controller = new AbortController()
    loadHistory({ signal: controller.signal }).then((data) => setServerItems(Array.isArray(data.items) ? data.items : [])).catch((requestError) => {
      if (requestError?.name !== 'AbortError') setError(requestError.message || 'We could not load scan history.')
    }).finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  const items = useMemo(() => mergeItems(serverItems, localItems, hiddenIds), [serverItems, localItems, hiddenIds])
  const filtered = useMemo(() => items.filter((item) => `${titleFor(item)} ${item.band || ''} ${item.source || ''} ${item.result?.scoring_method || ''}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())), [items, query])
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const visible = filtered.slice((page - 1) * pageSize, page * pageSize)

  function removeItem(item) {
    hideHistoryIds([item.id])
    removeLocalHistoryIds([item.id])
    setHiddenIds((ids) => [...new Set([...ids, item.id])])
    setLocalItems(readLocalHistory())
  }

  function clearHistory() {
    hideHistoryIds(items.map((item) => item.id))
    removeLocalHistoryIds(items.map((item) => item.id))
    setHiddenIds(readHiddenHistoryIds())
    setLocalItems([])
    setConfirmClear(false)
  }

  function reopen(item) {
    if (!item.result) {
      setError('This saved check cannot be reopened.')
      return
    }
    writeCurrentResult(item.result)
    navigate('/results')
  }

  useEffect(() => { setPage((current) => Math.min(current, pageCount)) }, [pageCount])
  return <div className="history-page">
    <PageIntro eyebrow="YOUR CHECKS" title="Scan history" action={<Link className="button button-primary inline-flex" to="/"><ArrowLeft size={17}/> New check</Link>}>Reopen a previous ingredient check from this browser.</PageIntro>
    <Card className="history-card"><div className="history-toolbar"><label className="search-field"><Search size={18} aria-hidden="true"/><span className="sr-only">Search scan history</span><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1) }} placeholder="Search your checks"/></label>{items.length > 0 && <Button variant="quiet" onClick={() => setConfirmClear(true)}><Trash2 size={16}/> Clear history</Button>}</div>
      {error && <Alert tone="warning">{error} Showing checks saved in this browser when available.</Alert>}
      {loading ? <div className="history-loading"><Spinner label="Loading your checks…"/><div className="skeleton-list"><span/><span/><span/></div></div> : visible.length > 0 ? <><div className="history-list">{visible.map((item) => { const source = sourceLabel(item.source); return <div className="history-row" key={item.id}><button className="history-open" onClick={() => reopen(item)}><span className="history-score">{item.score ?? '—'}</span><span className="history-info"><strong>{titleFor(item)}</strong><small>{dateFor(item)} · {source.label}</small><span className={`history-band band-${item.band === 'Low Risk' ? 'low' : item.band === 'High Risk' ? 'high' : 'medium'}`}>{item.band || 'Limited assessment'}</span></span><span className="history-source" aria-hidden="true">{source.icon}</span><ArrowRight className="history-arrow" size={18} aria-hidden="true"/></button><button className="icon-button" onClick={() => removeItem(item)} aria-label={`Remove ${titleFor(item)} from this browser`}><X size={17}/></button></div> })}</div><div className="history-pagination"><span>Page {page} of {pageCount}</span><div><button className="icon-button" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1} aria-label="Previous page"><ArrowLeft size={17}/></button><button className="icon-button" onClick={() => setPage((current) => Math.min(pageCount, current + 1))} disabled={page === pageCount} aria-label="Next page"><ArrowRight size={17}/></button></div></div></> : <EmptyState icon={<Clock3 size={27}/>} title={query ? 'No checks match that search' : 'No checks yet'}>{query ? 'Try a different search term.' : 'Completed ingredient checks will appear here.'}</EmptyState>}
    </Card>
    <p className="history-note">History is saved for this browser session. Removing a check hides it here and clearing site data removes local copies.</p>
    {confirmClear && <div className="dialog-backdrop" role="presentation"><div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="clear-history-title"><h2 id="clear-history-title">Clear scan history?</h2><p>This removes the checks from this browser view. You can start a new check at any time.</p><div className="action-row"><Button variant="secondary" onClick={() => setConfirmClear(false)}>Cancel</Button><Button variant="danger" onClick={clearHistory}>Clear history</Button></div></div></div>}
  </div>
}
