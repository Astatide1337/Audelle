import { useMemo } from 'react'

interface AudioVisualizerProps {
  isPlaying: boolean
  playbackTime: number
  trackId: string
}

const BAR_COUNT = 16

interface BarProfile {
  base: number
  phase: number
  speed: number
  harmonic: number
}

function barProfilesForTrack(trackId: string): BarProfile[] {
  let hash = 2166136261
  for (const character of trackId) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619)

  const next = () => {
    hash = Math.imul(hash ^ 0x9e3779b9, 16777619)
    return (hash >>> 0) / 0xffffffff
  }

  return Array.from({ length: BAR_COUNT }, (_, index) => {
    return {
      base: 20 + next() * 48,
      phase: next() * Math.PI * 2 + index * 0.4,
      speed: 1.2 + next() * 1.2 + index * 0.025,
      harmonic: 0.25 + next() * 0.5,
    }
  })
}

/**
 * A timing-synced visualizer driven by the YouTube player's playback clock.
 * The IFrame API does not expose frequency or amplitude samples, so this is
 * intentionally a deterministic per-track rhythm rather than a claim of raw
 * spectrum analysis. A same-origin audio source would be required for that.
 */
export function AudioVisualizer({ isPlaying, playbackTime, trackId }: AudioVisualizerProps) {
  const profiles = useMemo(() => barProfilesForTrack(trackId), [trackId])

  return (
    <div
      className={`audio-visualizer ${isPlaying ? 'is-playing' : ''}`}
      aria-label={isPlaying ? 'Audio visualizer, playing' : 'Audio visualizer, paused'}
      role="img"
    >
      {profiles.map((profile, index) => {
        const primary = Math.sin(playbackTime * profile.speed + profile.phase)
        const secondary = Math.sin(playbackTime * (profile.speed * 1.73) + profile.phase * 0.7)
        const harmonic = Math.sin(playbackTime * (profile.speed * 0.41) + profile.phase * 1.9)
        const energy = isPlaying ? 0.52 + primary * 0.26 + secondary * profile.harmonic * 0.18 + harmonic * 0.08 : 0.28
        const height = Math.max(8, Math.min(100, profile.base * (0.55 + energy)))
        return (
          <span
            key={index}
            className="audio-visualizer__bar"
            style={{ height: `${height}%` }}
          />
        )
      })}
    </div>
  )
}
