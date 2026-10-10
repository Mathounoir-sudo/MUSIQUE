// Lecture des notes de la tablature avec Web Audio (synthèse simple).
import type { TabEvent } from './api'

const midiToHz = (m: number) => 440 * Math.pow(2, (m - 69) / 12)

export class TabSynth {
  private ctx: AudioContext | null = null
  private nodes: OscillatorNode[] = []
  private raf = 0

  get playing() {
    return this.nodes.length > 0
  }

  /** Joue les événements au rythme de la tablature (temps quantifiés). */
  play(events: TabEvent[], tempo: number, speed: number, onIndex: (i: number) => void, onEnd: () => void) {
    this.stop()
    const ctx = (this.ctx ??= new AudioContext())
    void ctx.resume()
    const beatSec = 60 / tempo / speed
    const t0 = ctx.currentTime + 0.1
    const master = ctx.createGain()
    master.gain.value = 0.18
    master.connect(ctx.destination)
    const times: number[] = []
    for (const ev of events) {
      const start = t0 + ev.beat * beatSec
      const dur = Math.max(0.08, ev.beats * beatSec * 0.92)
      times.push(start)
      for (const n of ev.notes) {
        const osc = ctx.createOscillator()
        const g = ctx.createGain()
        osc.type = 'triangle'
        osc.frequency.value = midiToHz(n.pitch)
        g.gain.setValueAtTime(0, start)
        g.gain.linearRampToValueAtTime(1 / Math.max(1, ev.notes.length * 0.7), start + 0.015)
        g.gain.setTargetAtTime(0, start + dur - 0.05, 0.03)
        osc.connect(g).connect(master)
        osc.start(start)
        osc.stop(start + dur + 0.2)
        this.nodes.push(osc)
      }
    }
    const last = events.length ? t0 + (events[events.length - 1].beat + events[events.length - 1].beats) * beatSec : t0
    const tick = () => {
      const now = ctx.currentTime
      if (now > last + 0.2) {
        this.stop()
        onIndex(-1)
        onEnd()
        return
      }
      let idx = -1
      for (let i = 0; i < times.length && times[i] <= now; i++) idx = i
      onIndex(idx)
      this.raf = requestAnimationFrame(tick)
    }
    this.raf = requestAnimationFrame(tick)
  }

  stop() {
    cancelAnimationFrame(this.raf)
    for (const n of this.nodes) {
      try {
        n.stop()
      } catch {
        /* déjà arrêté */
      }
    }
    this.nodes = []
  }
}
