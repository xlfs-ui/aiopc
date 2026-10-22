/** Delegated pointer feedback. No animations run against reduced motion. */
export function installInterfaceMotion() {
  const media = window.matchMedia('(prefers-reduced-motion: reduce)')
  const timers = new Map<HTMLElement, ReturnType<typeof setTimeout>>()
  let frame = 0
  let card: HTMLElement | null = null
  const reduced = () => media.matches || document.documentElement.dataset.motion === 'reduced'
  function move(event: PointerEvent) {
    if (reduced() || event.pointerType !== 'mouse' || !(event.target instanceof Element)) return
    const target = event.target.closest<HTMLElement>('.metric-card,.service-card,.resource-card,.policy-card,.activity-card,.civic-kpi,.civic-card,.civic-place-grid>article')
    if (card && card !== target) card.classList.remove('has-pointer-glow')
    card = target
    cancelAnimationFrame(frame)
    if (!target) return
    frame = requestAnimationFrame(() => {
      if (!target.isConnected || reduced()) return
      const bounds = target.getBoundingClientRect()
      target.style.setProperty('--pointer-x', `${event.clientX - bounds.left}px`)
      target.style.setProperty('--pointer-y', `${event.clientY - bounds.top}px`)
      target.classList.add('has-pointer-glow')
    })
  }
  function press(event: PointerEvent) {
    if (reduced() || event.button !== 0 || !(event.target instanceof Element)) return
    const button = event.target.closest<HTMLElement>('.button,.auth-submit,.service-grid button,.nav-item,.resource-open')
    if (!button || (button instanceof HTMLButtonElement && button.disabled)) return
    const bounds = button.getBoundingClientRect()
    button.style.setProperty('--press-x', `${event.clientX - bounds.left}px`)
    button.style.setProperty('--press-y', `${event.clientY - bounds.top}px`)
    button.classList.remove('is-pressed')
    requestAnimationFrame(() => { if (button.isConnected && !reduced()) button.classList.add('is-pressed') })
    clearTimeout(timers.get(button))
    timers.set(button, setTimeout(() => { button.classList.remove('is-pressed'); timers.delete(button) }, 650))
  }
  function leave() { card?.classList.remove('has-pointer-glow'); card = null; cancelAnimationFrame(frame) }
  document.addEventListener('pointermove', move, { passive: true })
  document.addEventListener('pointerdown', press, { passive: true })
  document.addEventListener('pointerleave', leave)
  return () => {
    document.removeEventListener('pointermove', move); document.removeEventListener('pointerdown', press); document.removeEventListener('pointerleave', leave)
    leave(); timers.forEach((timer, button) => { clearTimeout(timer); button.classList.remove('is-pressed') }); timers.clear()
  }
}
