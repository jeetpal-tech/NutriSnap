import React from 'react'
import { AlertCircle, ArrowRight, Check, ChevronDown, ChevronUp, LoaderCircle } from 'lucide-react'

export function Button({ variant = 'primary', className = '', children, ...props }) {
  return <button className={`button button-${variant} ${className}`} {...props}>{children}</button>
}

export function Card({ className = '', children, ...props }) {
  return <section className={`brutal-card ${className}`} {...props}>{children}</section>
}

export function Spinner({ label = 'Working…', className = '' }) {
  return <div className={`flex items-center gap-3 text-sm text-muted ${className}`} role="status"><LoaderCircle className="animate-spin" size={18} aria-hidden="true"/><span>{label}</span></div>
}

export function Alert({ children, tone = 'danger' }) {
  return <div className={`alert alert-${tone}`} role="alert"><AlertCircle size={18} className="mt-0.5 shrink-0" aria-hidden="true"/><p>{children}</p></div>
}

export function EmptyState({ icon, title, children, action }) {
  return <div className="empty-state">{icon && <div className="empty-icon" aria-hidden="true">{icon}</div>}<h2>{title}</h2>{children && <p>{children}</p>}{action && <div className="mt-5">{action}</div>}</div>
}

export function PageIntro({ eyebrow, title, children, action }) {
  return <div className="page-intro"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{children && <p className="page-intro-copy">{children}</p>}</div>{action}</div>
}

export function ScoreRing({ score = 0, band = 'Moderate Risk' }) {
  const radius = 48
  const circumference = 2 * Math.PI * radius
  const safeScore = Math.max(0, Math.min(100, Number(score) || 0))
  const tone = band === 'Low Risk' ? 'score-low' : band === 'High Risk' ? 'score-high' : 'score-medium'
  return <div className={`score-ring-wrap ${tone}`}>
    <svg className="score-ring-svg" viewBox="0 0 120 120" role="img" aria-label={`Score ${safeScore} out of 100. ${band}.`}>
      <circle cx="60" cy="60" r={radius} className="score-track"/>
      <circle cx="60" cy="60" r={radius} className="score-progress" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - safeScore / 100)}/>
    </svg>
    <div className="score-ring-label"><strong>{safeScore}</strong><span>/ 100</span><b>{band}</b></div>
  </div>
}

export function ConcernBadge({ level = 'unknown', label }) {
  const known = ['low', 'medium', 'high'].includes(level) ? level : 'unknown'
  return <span className={`concern-badge concern-${known}`}>{label || (known === 'unknown' ? 'Not assessed' : `${known} concern`)}</span>
}

export function MethodBadge({ result }) {
  const assisted = result?.scoring_method === 'ml_assisted'
  return <span className={`method-badge ${assisted ? 'method-ai' : 'method-rules'}`}><span className="method-dot" aria-hidden="true"/>{assisted ? 'AI-assisted estimate' : 'Ingredient-rules estimate'}</span>
}

export function AccordionButton({ open, children, ...props }) {
  return <button className="accordion-button" aria-expanded={open} {...props}><span className="min-w-0 flex-1 text-left">{children}</span>{open ? <ChevronUp size={18} aria-hidden="true"/> : <ChevronDown size={18} aria-hidden="true"/>}</button>
}

export function LinkAction({ children, ...props }) {
  return <button className="link-action" {...props}>{children}<ArrowRight size={16} aria-hidden="true"/></button>
}

export function VisuallyHidden({ children }) {
  return <span className="sr-only">{children}</span>
}

export function SuccessMark() {
  return <span className="success-mark" aria-hidden="true"><Check size={16}/></span>
}
