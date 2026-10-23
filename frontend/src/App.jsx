import React from 'react'
import { Leaf, History, ScanLine } from 'lucide-react'
import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import ScanPage from './pages/ScanPage.jsx'
import ResultsPage from './pages/ResultsPage.jsx'
import HistoryPage from './pages/HistoryPage.jsx'

function NavItem({ to, children, icon }) {
  return <NavLink to={to} end={to === '/'} className={({ isActive }) => `top-nav-link ${isActive ? 'top-nav-link-active' : ''}`}>{icon}{children}</NavLink>
}

function AppShell() {
  return <div className="app-shell"><header className="site-header"><div className="site-header-inner"><Link to="/" className="brand"><span className="brand-mark"><Leaf size={19}/></span><span>Nutri<span>Snap</span></span></Link><nav className="top-nav" aria-label="Main navigation"><NavItem to="/" icon={<ScanLine size={17}/>} >Scan</NavItem><NavItem to="/history" icon={<History size={17}/>} >History</NavItem></nav></div></header><main className="site-main"><Routes><Route path="/" element={<ScanPage/>}/><Route path="/results" element={<ResultsPage/>}/><Route path="/history" element={<HistoryPage/>}/><Route path="*" element={<Navigate to="/" replace/>}/></Routes></main><footer className="site-footer"><span>NutriSnap</span><span>Ingredient estimates for everyday shopping.</span><span>Not medical advice · Open Food Facts attribution included where relevant.</span></footer></div>
}

export default function App() {
  return <AppShell/>
}
