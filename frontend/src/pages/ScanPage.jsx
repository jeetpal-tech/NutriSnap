import React from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Camera, ClipboardPaste, FileImage, ImagePlus, Leaf, RefreshCw, Sparkles, Type, Upload, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Spinner } from '../components/ui.jsx'
import { analyzeIngredients, scanLabelImage } from '../lib/api.js'
import { saveLocalHistory, writeCurrentResult } from '../lib/storage.js'

const examples = [
  { label: 'Masala snack', text: 'Potato, palmolein, salt, spices, flavour enhancer (INS 621)' },
  { label: 'Everyday cereal', text: 'Whole wheat, oats, raisins, almonds, honey' },
  { label: 'Simple breakfast', text: 'Oats, roasted chana, peanuts, salt' },
]

function stopTracks(stream) {
  stream?.getTracks().forEach((track) => track.stop())
}

async function resizeImage(file) {
  if (!file.type.startsWith('image/')) throw new Error('Choose an image file such as JPG, PNG, or WEBP.')
  if (file.size > 5 * 1024 * 1024) throw new Error('That image is larger than 5 MB. Choose a smaller label photo.')
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, 1280 / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  const blob = await new Promise((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error('That image could not be prepared.')), 'image/jpeg', 0.86))
  return new File([blob], 'nutrisnap-label.jpg', { type: 'image/jpeg' })
}

export default function ScanPage() {
  const navigate = useNavigate()
  const fileRef = useRef(null)
  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const requestRef = useRef(null)
  const requestIdRef = useRef(0)
  const initialText = new URLSearchParams(window.location.search).get('ingredients') || ''
  const [mode, setMode] = useState(initialText ? 'paste' : null)
  const [text, setText] = useState(initialText)
  const [cameraState, setCameraState] = useState('idle')
  const [cameraError, setCameraError] = useState('')
  const [image, setImage] = useState(null)
  const [preview, setPreview] = useState('')
  const [reviewText, setReviewText] = useState('')
  const [reviewSource, setReviewSource] = useState('camera')
  const [stage, setStage] = useState('input')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const cancelRequest = useCallback(() => {
    requestRef.current?.abort()
    requestRef.current = null
  }, [])

  const stopCamera = useCallback(() => {
    stopTracks(streamRef.current)
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setCameraState((current) => current === 'ready' || current === 'starting' ? 'idle' : current)
  }, [])

  useEffect(() => () => {
    cancelRequest()
    stopTracks(streamRef.current)
    if (preview) URL.revokeObjectURL(preview)
  }, [cancelRequest, preview])

  useEffect(() => {
    if (videoRef.current && streamRef.current) videoRef.current.srcObject = streamRef.current
  }, [cameraState])

  function chooseMode(nextMode) {
    setError('')
    setStage('input')
    if (nextMode !== 'camera') stopCamera()
    setMode(nextMode)
  }

  async function openCamera() {
    setMode('camera')
    setError('')
    setCameraError('')
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraState('error')
      setCameraError('Camera access is not available in this browser. Upload a photo or paste the label instead.')
      return
    }
    setCameraState('starting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
      streamRef.current = stream
      setCameraState('ready')
      requestAnimationFrame(() => { if (videoRef.current) videoRef.current.srcObject = stream })
    } catch {
      setCameraState('error')
      setCameraError('Camera permission was denied or no camera is available. Upload a photo or paste the ingredients instead.')
    }
  }

  async function captureFrame() {
    try {
      const video = videoRef.current
      if (!video?.videoWidth) throw new Error('The camera is not ready yet. Try again in a moment.')
      const canvas = document.createElement('canvas')
      const scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight))
      canvas.width = Math.round(video.videoWidth * scale)
      canvas.height = Math.round(video.videoHeight * scale)
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
      const blob = await new Promise((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error('The camera frame could not be captured.')), 'image/jpeg', 0.86))
      await setImageFile(new File([blob], 'nutrisnap-camera.jpg', { type: 'image/jpeg' }), 'camera')
      stopCamera()
      setMode('upload')
    } catch (captureError) {
      setError(captureError.message || 'The camera frame could not be captured.')
    }
  }

  async function setImageFile(file, source = 'upload') {
    try {
      const prepared = await resizeImage(file)
      if (preview) URL.revokeObjectURL(preview)
      setImage(prepared)
      setPreview(URL.createObjectURL(prepared))
      setReviewSource(source)
      setError('')
      setStage('input')
    } catch (imageError) {
      setError(imageError.message || 'That image could not be used.')
    }
  }

  async function chooseFile(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) await setImageFile(file, 'upload')
  }

  async function pasteFromClipboard() {
    try {
      setText(await navigator.clipboard.readText())
      setError('')
    } catch {
      setError('Clipboard access was blocked. Paste directly into the ingredient box instead.')
    }
  }

  async function runRequest(work, onSuccess) {
    cancelRequest()
    const controller = new AbortController()
    requestRef.current = controller
    const requestId = ++requestIdRef.current
    let timedOut = false
    const timeout = window.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, 35000)
    setBusy(true)
    setError('')
    try {
      const result = await work(controller.signal)
      if (requestId !== requestIdRef.current) return
      onSuccess(result)
    } catch (requestError) {
      if (requestId === requestIdRef.current) {
        if (timedOut) setError('This check took too long. Try again with a clearer label or pasted text.')
        else if (requestError?.name !== 'AbortError') setError(requestError.message || 'We could not complete that check. Try again.')
      }
    } finally {
      window.clearTimeout(timeout)
      if (requestId === requestIdRef.current) {
        setBusy(false)
        requestRef.current = null
      }
    }
  }

  function finishResult(result, inputType = 'paste') {
    if (result.status !== 'ok') {
      setError(result.message || 'Please enter a complete ingredient list.')
      return
    }
    const finalResult = { ...result, source: inputType, detected_text: inputType === 'paste' ? undefined : result.detected_text }
    writeCurrentResult(finalResult)
    saveLocalHistory(finalResult, inputType)
    navigate('/results')
  }

  function analyzeText() {
    const value = text.trim()
    if (!value) {
      setError('Paste or type the ingredient list before checking it.')
      return
    }
    runRequest((signal) => analyzeIngredients(value, { signal }), (result) => finishResult(result, 'paste'))
  }

  function analyzePhoto() {
    if (!image) return
    runRequest((signal) => scanLabelImage(image, { signal }), (result) => {
      if (result.status === 'ocr_unavailable' || result.status === 'no_ingredients_found') {
        setError(result.message || 'We could not read this photo. Try a clearer image or paste the ingredients.')
        return
      }
      if (result.status !== 'ok' || !result.detected_text?.trim()) {
        setError('We could not find an ingredient list in this photo. Try a clearer image or paste the ingredients.')
        return
      }
      setReviewText(result.detected_text)
      setStage('review')
    })
  }

  function confirmPhotoText() {
    const value = reviewText.trim()
    if (!value) {
      setError('Add the ingredient text before checking it.')
      return
    }
    runRequest((signal) => analyzeIngredients(value, { signal }), (result) => finishResult({ ...result, source: reviewSource, detected_text: value }, reviewSource))
  }

  useEffect(() => {
    const autorun = new URLSearchParams(window.location.search).get('autorun') === '1'
    if (!autorun || !initialText.trim()) return undefined
    const timer = window.setTimeout(() => analyzeText(), 0)
    return () => window.clearTimeout(timer)
  }, [initialText])

  const hasPhoto = Boolean(image && preview)
  return <div className="scan-page">
    <section className="scan-hero">
      <div className="hero-stamp"><Leaf size={18} aria-hidden="true"/> LABEL CHECK / INDIA</div>
      <h1>Make the label<br/><span>make sense.</span></h1>
      <p>Check packaged-food ingredients in a few seconds. Get a clear estimate, ingredient details, and cautious next steps.</p>
    </section>

    <Card className="scan-workspace">
      <div className="workspace-heading"><div><p className="eyebrow">START A CHECK</p><h2>How do you want to share the label?</h2></div><span className="workspace-note">No account needed</span></div>
      <div className="input-choices" role="tablist" aria-label="Ingredient input method">
        <button className={`input-choice ${mode === 'camera' ? 'input-choice-active' : ''}`} onClick={openCamera} role="tab" aria-selected={mode === 'camera'}><span className="choice-icon choice-lime"><Camera size={21}/></span><span><strong>Camera</strong><small>Read a label live</small></span></button>
        <button className={`input-choice ${mode === 'upload' ? 'input-choice-active' : ''}`} onClick={() => { chooseMode('upload'); fileRef.current?.click() }} role="tab" aria-selected={mode === 'upload'}><span className="choice-icon choice-yellow"><Upload size={21}/></span><span><strong>Upload</strong><small>Choose a label photo</small></span></button>
        <button className={`input-choice ${mode === 'paste' ? 'input-choice-active' : ''}`} onClick={() => chooseMode('paste')} role="tab" aria-selected={mode === 'paste'}><span className="choice-icon choice-lavender"><Type size={21}/></span><span><strong>Paste text</strong><small>Type it yourself</small></span></button>
      </div>
      <input ref={fileRef} type="file" accept="image/*" className="sr-only" onChange={chooseFile}/>

      {mode === 'camera' && <div className="capture-panel">
        <div className="capture-frame">
          {cameraState === 'ready' && <video ref={videoRef} autoPlay muted playsInline aria-label="Camera preview"/>}
          {cameraState === 'starting' && <div className="capture-placeholder"><Spinner label="Opening the camera…"/></div>}
          {cameraState === 'error' && <div className="capture-placeholder"><Camera size={32}/><p>{cameraError}</p></div>}
          {cameraState === 'idle' && <div className="capture-placeholder"><Camera size={32}/><p>Select Camera to request access.</p></div>}
          {cameraState === 'ready' && <div className="frame-guide" aria-hidden="true"/>}
        </div>
        {cameraError && cameraState !== 'error' && <Alert>{cameraError}</Alert>}
        <div className="capture-guidance"><strong>For a better read</strong><span>Use bright, even light. Keep the full ingredient panel inside the frame.</span></div>
        <div className="action-row"><Button variant="secondary" onClick={stopCamera}><X size={17}/> Close camera</Button><Button onClick={captureFrame} disabled={cameraState !== 'ready' || busy}><Camera size={17}/> Capture label</Button></div>
      </div>}

      {mode === 'upload' && stage !== 'review' && <div className="upload-panel">
        {hasPhoto ? <div className="image-preview-wrap"><img src={preview} alt="Selected ingredient label"/><button className="remove-image" onClick={() => { setImage(null); URL.revokeObjectURL(preview); setPreview(''); setStage('input') }} aria-label="Remove selected image"><X size={17}/></button></div> : <button className="upload-dropzone" onClick={() => fileRef.current?.click()}><ImagePlus size={30}/><strong>Choose a clear label photo</strong><span>JPG, PNG, or WEBP · up to 5 MB</span></button>}
        {hasPhoto && <div className="action-row"><Button variant="secondary" onClick={() => fileRef.current?.click()}><RefreshCw size={17}/> Replace photo</Button><Button onClick={analyzePhoto} disabled={busy}>{busy ? <Spinner label="Reading photo…"/> : <><Sparkles size={17}/> Read ingredients</>}</Button></div>}
      </div>}

      {stage === 'review' && <div className="review-panel"><div className="review-heading"><div><p className="eyebrow">CHECK THE TRANSCRIPTION</p><h3>Does this match your label?</h3></div><span className="source-tag"><FileImage size={15}/> {reviewSource === 'camera' ? 'Camera photo' : 'Uploaded photo'}</span></div><p className="review-copy">Correct any missed words before the final ingredient check. We do not guess text that the photo does not show clearly.</p><textarea value={reviewText} onChange={(event) => setReviewText(event.target.value)} maxLength={4000} aria-label="Review extracted ingredient text"/><div className="action-row"><Button variant="secondary" onClick={() => { setStage('input'); setMode('upload') }}><RefreshCw size={17}/> Try another photo</Button><Button onClick={confirmPhotoText} disabled={busy || !reviewText.trim()}>{busy ? <Spinner label="Checking…"/> : <><Sparkles size={17}/> Check these ingredients</>}</Button></div></div>}

      {mode === 'paste' && stage !== 'review' && <div className="paste-panel"><div className="paste-toolbar"><label htmlFor="ingredients">Ingredient list</label><button className="paste-button" onClick={pasteFromClipboard}><ClipboardPaste size={16}/> Paste from clipboard</button></div><textarea id="ingredients" value={text} onChange={(event) => setText(event.target.value)} maxLength={4000} placeholder="Example: whole wheat flour, sugar, palmolein, salt, spices…"/><div className="paste-footer"><span>{text.length}/4000 characters</span><Button onClick={analyzeText} disabled={busy || !text.trim()}>{busy ? <Spinner label="Checking…"/> : <><Sparkles size={17}/> Check ingredients</>}</Button></div></div>}

      {error && <Alert>{error}</Alert>}
    </Card>

    <section className="examples-section"><div className="section-label"><span>TRY A SAMPLE</span><i/></div><div className="example-grid">{examples.map((example) => <button key={example.label} className="example-card" onClick={() => { setMode('paste'); setText(example.text); setError('') }}><span>{example.label}</span><small>{example.text}</small></button>)}</div></section>
    <div className="scan-trust"><span><span className="trust-dot"/>Your ingredient text is used only to run this check.</span><span>Results are estimates, not medical advice.</span></div>
  </div>
}
