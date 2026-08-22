interface ExportStart {
  session_id: string
  user_code: string
  verification_url: string
  expires_in: number
  interval: number
}

interface ExportPoll {
  status: 'pending' | 'complete'
  authorized_session_id: string | null
}

export class ExportAccessDeniedError extends Error {}

async function exportRequest<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (response.status === 403) throw new ExportAccessDeniedError('Google has not approved this OAuth test account.')
  if (!response.ok) throw new Error(`Export request failed (${response.status})`)
  return response.json() as Promise<T>
}

export function startYouTubeMusicExport() {
  return exportRequest<ExportStart>('/api/export/youtube-music/start')
}

export function pollYouTubeMusicExport(sessionId: string) {
  return exportRequest<ExportPoll>('/api/export/youtube-music/poll', { session_id: sessionId })
}

/** Keep the user's vibe recognizable while respecting YouTube's title limit. */
export function playlistNameFromPrompt(prompt: string): string {
  const normalized = prompt.replace(/\s+/g, ' ').trim()
  return Array.from(normalized || 'Audelle playlist').slice(0, 150).join('')
}

export async function createYouTubeMusicPlaylist(authorizedSessionId: string, name: string, trackIds: string[]) {
  return exportRequest<{ external_url: string }>('/api/export/youtube-music/create', {
    authorized_session_id: authorizedSessionId,
    name,
    description: 'Made with Audelle',
    track_ids: trackIds,
  })
}
