import React from 'react'
import { useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, ChevronDown, FileText, History, Info, Leaf, RotateCcw, ShieldCheck, Sparkles, TriangleAlert, Upload } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { AccordionButton, Alert, Button, Card, ConcernBadge, EmptyState, LinkAction, MethodBadge, ScoreRing } from '../components/ui.jsx'
import { analyzeIngredients } from '../lib/api.js'
import { readCurrentResult, saveLocalHistory, writeCurrentResult } from '../lib/storage.js'

const fallbackCopy = {
  forced_rules: 'The ingredient rules produced this estimate.',
  ml_disabled: 'The ingredient rules produced this estimate.',
  model_loading: 'The AI review was still starting, so the ingredient rules produced this estimate.',
  model_error: 'The AI review was unavailable, so the ingredient rules produced this estimate.',
  model_timeout: 'The AI review took too long, so the ingredient rules produced this estimate.',
  unsupported_language: 'This text could not be reviewed by the AI model, so the ingredient rules produced this estimate.',
  low_confidence: 'The AI review was not confident enough, so the ingredient rules produced this estimate.',
  weak_class_uncertain: 'The AI review was not confident enough, so the ingredient rules produced this estimate.',
  ambiguous_prediction: 'The AI review was not confident enough, so the ingredient rules produced this estimate.',
  ml_rule_disagreement: 'The AI review and ingredient rules differed, so the more cautious ingredient-rules estimate is shown.',
}

function normalize(value = '') {
  return String(value).trim().toLocaleLowerCase()
}

function inputLabel(source) {
  if (source === 'camera') return 'Camera photo'
  if (source === 'upload') return 'Uploaded photo'
  return 'Pasted ingredients'
}

function assessmentCopy(result) {
  if (result.low_coverage_warning) return 'This is a limited assessment because some ingredients could not be matched.'
  if (result.band === 'High Risk') return 'Several ingredients may warrant a closer look. Review the details below for context.'
  if (result.band === 'Moderate Risk') return 'Some ingredients may be worth comparing when you shop. Review the details below.'
  return 'The listed ingredients show fewer flagged concerns in this estimate. Ingredient lists do not capture every nutrition detail.'
}

function infoForIngredient(ingredient, info) {
  const keys = [ingredient.raw, ingredient.name, ingredient.canonical].filter(Boolean).map(normalize)
  return info.find((item) => keys.includes(normalize(item.name)))
}

function ingredientLevel(ingredient, info) {
  return info?.risk_level || info?.concern_level || (ingredient.matched ? ingredient.risk : 'unknown')
}

function NovaCard({ badge }) {
  if (!badge || badge.source === 'unavailable' || !badge.group) return null
  const labels = { 1: 'Minimally processed', 2: 'Processed culinary ingredient', 3: 'Processed food', 4: 'Ultra-processed food' }
  return <Card className="nova-card"><div className="nova-mark"><Leaf size={18}/></div><div><p className="eyebrow">PROCESSING SIGNAL</p><h3>NOVA {badge.group} <span>{labels[badge.group] || 'Processing level'}</span></h3><p>NOVA describes the extent of industrial processing, not nutrient content.</p>{badge.source === 'rule_estimate' && <small>Estimated from ingredient markers.</small>}</div></Card>
}

function IngredientDetails({ result }) {
  const [open, setOpen] = useState(null)
  const info = result.ingredient_info || []
  const ingredients = useMemo(() => [...(result.ingredients || [])].map((ingredient, index) => ({ ingredient, index, info: infoForIngredient(ingredient, info) })), [result.ingredients, info])
  return <Card className="detail-card"><div className="card-heading"><div><p className="eyebrow">INGREDIENT DETAILS</p><h2>What is in this label?</h2></div><span className="count-tag">{ingredients.length} items</span></div><div className="ingredient-list">{ingredients.map(({ ingredient, index, info: itemInfo }) => { const level = ingredientLevel(ingredient, itemInfo); const isOpen = open === index; return <div className="ingredient-item" key={`${ingredient.position}-${index}`}><AccordionButton open={isOpen} onClick={() => setOpen(isOpen ? null : index)}><span className="ingredient-name"><span className={`ingredient-marker marker-${level}`} aria-hidden="true"/><span><strong>{ingredient.canonical || ingredient.name || ingredient.raw}</strong><small>{ingredient.matched ? ingredient.raw : 'Not enough information to assess this ingredient'}</small></span></span><span className="ingredient-meta"><ConcernBadge level={level}/>{typeof ingredient.points === 'number' && ingredient.points !== 0 && <b className={ingredient.points < 0 ? 'points-negative' : 'points-positive'}>{ingredient.points > 0 ? '+' : ''}{Number(ingredient.points).toFixed(0)}</b>}</span></AccordionButton>{isOpen && <div className="ingredient-explanation">{itemInfo ? <><p>{itemInfo.what_it_is}</p><p>{itemInfo.health_note}</p><small className="provenance-note">{itemInfo.ai_generated ? 'AI-generated general information; not a clinical risk assessment.' : itemInfo.verified ? 'Evidence-backed ingredient note.' : 'General ingredient information.'}</small></> : ingredient.explanation && ingredient.verified ? <><p>{ingredient.explanation}</p><small className="provenance-note">Evidence-backed ingredient note.</small></> : <p className="unknown-copy">There is not enough verified information here to describe this ingredient. Unknown does not mean safe.</p>}</div>}</div> })}</div></Card>
}

function Alternatives({ items }) {
  if (!items?.length) return null
  const aiGenerated = items.some((item) => item.ai_generated || item.source === 'gemini')
  return <Card className="alternatives-card"><div className="card-heading"><div><p className="eyebrow">IF YOU ARE COMPARING OPTIONS</p><h2>Healthier options to compare</h2></div>{aiGenerated && <span className="ai-tag"><Sparkles size={14}/> AI-generated</span>}</div><p className="card-copy">Suggestions are based on this ingredient list when Gemini is unavailable. Compare nutrition labels; these are not medical advice.</p><div className="alternative-grid">{items.slice(0, 3).map((item, index) => <div className="alternative-item" key={`${item.type}-${index}`}><span>0{index + 1}</span><div><strong>{item.type}</strong><p>{item.reason}</p></div></div>)}</div></Card>
}

export default function ResultsPage() {
  const navigate = useNavigate()
  const [result, setResult] = useState(readCurrentResult)
  const [openReview, setOpenReview] = useState(false)
  const [editText, setEditText] = useState(result?.detected_text || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function reanalyze() {
    if (!editText.trim()) return
    setBusy(true)
    setError('')
    try {
      const next = await analyzeIngredients(editText.trim())
      if (next.status !== 'ok') throw new Error(next.message || 'Please enter a complete ingredient list.')
      const merged = { ...next, source: result?.source || 'camera', detected_text: editText.trim() }
      setResult(merged)
      writeCurrentResult(merged)
      saveLocalHistory(merged, merged.source)
      setOpenReview(false)
    } catch (requestError) {
      if (requestError?.name !== 'AbortError') setError(requestError.message || 'We could not re-check that text.')
    } finally {
      setBusy(false)
    }
  }

  if (!result) return <EmptyState icon={<FileText size={26}/>} title="No ingredient check yet" action={<Link className="button button-primary inline-flex" to="/">Start a check <ArrowRight size={17}/></Link>}>Scan a label or paste an ingredient list to see the assessment here.</EmptyState>
  if (result.status !== 'ok') return <EmptyState icon={<TriangleAlert size={26}/>} title="This label could not be assessed" action={<Link className="button button-primary inline-flex" to="/">Try another label <RotateCcw size={17}/></Link>}>{result.message || 'Try a clearer ingredient list.'}</EmptyState>

  const source = inputLabel(result.source)
  const fallback = fallbackCopy[result.fallback_reason]
  const concerns = result.flags || []
  return <div className="results-page">
    <div className="results-topbar"><button className="back-action" onClick={() => navigate('/')}><ArrowLeft size={17}/> New check</button><div className="results-actions"><span className="source-tag">{result.source === 'paste' ? <TypeIcon/> : <Upload size={15}/>} {source}</span><Link className="history-action" to="/history"><History size={16}/> History</Link></div></div>
    <header className="results-heading"><div><p className="eyebrow">YOUR INGREDIENT CHECK</p><h1>Here is the readout.</h1><p>{assessmentCopy(result)}</p></div><MethodBadge result={result}/></header>

    <section className="assessment-grid"><Card className={`score-card score-card-${result.band === 'Low Risk' ? 'low' : result.band === 'High Risk' ? 'high' : 'medium'}`}><div className="score-card-top"><span className="score-label">NUTRISNAP ESTIMATE</span><span className="estimate-tag"><ShieldCheck size={15}/> Cautious by design</span></div><div className="score-card-body"><ScoreRing score={result.score} band={result.band}/><div className="score-summary"><p className="score-summary-label">Overall assessment</p><h2>{result.band}</h2><p>{fallback || 'This estimate uses the ingredient list and transparent scoring rules.'}</p>{result.low_coverage_warning && <div className="limited-note"><TriangleAlert size={16}/><span>Some ingredients could not be assessed.</span></div>}</div></div></Card><div className="side-signal-column"><Card className="signal-card"><div className="signal-number">{concerns.length}</div><div><p className="eyebrow">THINGS TO CONSIDER</p><h3>{concerns.length ? 'Flagged ingredients' : 'No flagged ingredients'}</h3><p>{concerns.length ? 'Open the details below for context.' : 'This does not mean the product is a complete nutrition assessment.'}</p></div></Card><NovaCard badge={result.nova_badge}/></div></section>

    {concerns.length > 0 && <Card className="concern-card"><div className="card-heading"><div><p className="eyebrow">KEY CONCERNS</p><h2>What shaped the estimate?</h2></div><Info size={20} aria-hidden="true"/></div><div className="concern-grid">{concerns.map((item) => <div className={`concern-item concern-item-${item.severity}`} key={item.flag}><span className="concern-symbol" aria-hidden="true">!</span><div><strong>{item.label}</strong><p>{item.severity === 'high' ? 'Higher-weight factor in this estimate.' : item.severity === 'medium' ? 'Meaningful factor in this estimate.' : 'Smaller factor in this estimate.'}</p></div></div>)}</div></Card>}
    <IngredientDetails result={result}/>
    <Alternatives items={result.alternatives}/>

    {result.detected_text && <Card className="review-result-card"><button className="review-toggle" onClick={() => setOpenReview(!openReview)} aria-expanded={openReview}><span><FileText size={17}/> Review label text used</span><ChevronDown className={openReview ? 'rotate-180' : ''} size={18}/></button>{openReview && <div className="review-result-content"><p>Photo text can be corrected and checked again. The assessment will be updated with the revised list.</p><textarea value={editText} onChange={(event) => setEditText(event.target.value)} maxLength={4000} aria-label="Ingredient text used for this check"/>{error && <Alert>{error}</Alert>}<Button onClick={reanalyze} disabled={busy || !editText.trim()}>{busy ? 'Checking…' : 'Check revised text'}</Button></div>}</Card>}

    <Card className="method-card"><div className="method-card-icon"><ShieldCheck size={20}/></div><div><h3>How to read this</h3><p>The NutriSnap score is an estimate based on the listed ingredients. It is not a clinical measurement. Unknown ingredients stay unknown, and AI-generated notes are labelled separately from verified evidence.</p></div></Card>
    <p className="results-disclaimer">{result.disclaimer || 'Informational only, not medical advice. NOVA reflects processing level, not toxicity.'} {result.attribution || 'Contains information from Open Food Facts (ODbL).'}</p>
    <div className="results-footer-actions"><Button variant="secondary" onClick={() => navigate('/')}><ArrowLeft size={17}/> New check</Button><LinkAction onClick={() => navigate('/history')}>View scan history</LinkAction></div>
  </div>
}

function TypeIcon() {
  return <span className="type-icon" aria-hidden="true">T</span>
}
