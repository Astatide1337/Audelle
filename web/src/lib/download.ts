/**
 * Playlist audio downloads.
 *
 * Each track is fetched one at a time through the server's validated
 * `/api/audio/{videoId}` proxy — callers only ever pass video IDs that came
 * from a playlist Audelle generated, never URLs. Files are packed client-side
 * into a ZIP with the STORE method. The server transcodes every response to
 * high-quality MP3, so recompressing it would only waste time.
 */

import type { Track } from './types'

const REQUEST_TIMEOUT_MS = 120_000
const MAX_FILENAME_LENGTH = 120

export class DownloadCancelledError extends Error {}

export interface DownloadResult {
  blob: Blob
  succeeded: { index: number; fileName: string }[]
  failed: { fileName: string; reason: string }[]
}

export interface DownloadCallbacks {
  /** A track started fetching. */
  onTrackStart?: (index: number) => void
  /** Byte progress within the current track; totalBytes may be unknown. */
  onTrackProgress?: (index: number, receivedBytes: number, totalBytes: number | null) => void
  /** A track finished and was added to the archive. */
  onTrackDone?: (index: number) => void
  /** A track failed permanently; the rest continue. */
  onTrackFailed?: (index: number, reason: string) => void
}

function extensionFor(contentType: string): string {
  if (!contentType.toLowerCase().includes('audio/mpeg')) {
    throw new Error('the download service returned audio in an unexpected format')
  }
  return '.mp3'
}

function baseFileName(track: Track): string {
  const label = [track.artists.join(', '), track.name].filter(Boolean).join(' — ')
  const cleaned = label.replace(/[\p{Cc}\\/:*?"<>|]/gu, ' ').replace(/\s+/g, ' ').trim()
  const bounded = Array.from(cleaned).slice(0, MAX_FILENAME_LENGTH).join('')
  return bounded.replace(/[ .]+$/, '') || `audelle-${track.id}`
}

function uniqueName(name: string, used: Set<string>): string {
  if (!used.has(name)) {
    used.add(name)
    return name
  }
  for (let n = 2; ; n++) {
    const candidate = `${name} (${n})`
    if (!used.has(candidate)) {
      used.add(candidate)
      return candidate
    }
  }
}

async function fetchTrackAudio(
  track: Track,
  outerSignal: AbortSignal | undefined,
  onProgress?: (receivedBytes: number, totalBytes: number | null) => void,
) {
  // Combine caller cancellation with a hard per-track timeout without relying
  // on AbortSignal.any/timeout, which older browsers lack.
  const controller = new AbortController()
  const abortFromOuter = () => controller.abort()
  outerSignal?.addEventListener('abort', abortFromOuter)
  const timer = setTimeout(() => controller.abort(new DOMException('timeout', 'TimeoutError')), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(`/api/audio/${encodeURIComponent(track.id)}`, { signal: controller.signal })
    if (outerSignal?.aborted) throw new DOMException('cancelled', 'AbortError')
    if (response.status === 404) throw new Error('no longer available on YouTube')
    if (response.status === 503) throw new Error('the download service is unavailable right now')
    if (!response.ok) throw new Error(`download failed (${response.status})`)

    const totalHeader = response.headers.get('Content-Length')
    const totalBytes = totalHeader ? Number(totalHeader) : null
    const contentType = response.headers.get('Content-Type') ?? ''
    if (!response.body) throw new Error('empty download')

    const reader = response.body.getReader()
    const chunks: Uint8Array[] = []
    let received = 0
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      chunks.push(value)
      received += value.byteLength
      onProgress?.(received, totalBytes)
    }
    return { chunks, totalBytes: totalBytes ?? received, contentType }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError' && outerSignal?.aborted) {
      throw new DownloadCancelledError()
    }
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new Error('timed out')
    }
    throw error instanceof Error ? error : new Error('download failed')
  } finally {
    clearTimeout(timer)
    outerSignal?.removeEventListener('abort', abortFromOuter)
  }
}

// --- Minimal ZIP (STORE) writer -------------------------------------------

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c >>> 0
  }
  return table
})()

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff
  for (let i = 0; i < data.length; i++) crc = CRC_TABLE[(crc ^ data[i]) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

interface ZipEntry {
  nameBytes: Uint8Array
  data: Uint8Array
  crc: number
  offset: number
  dosTime: number
  dosDate: number
}

function dosDateTime(date: Date): { dosTime: number; dosDate: number } {
  const dosTime = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2)
  const dosDate = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate()
  return { dosTime, dosDate }
}

export function buildZip(files: { name: string; data: Uint8Array }[]): Blob {
  const encoder = new TextEncoder()
  const { dosTime, dosDate } = dosDateTime(new Date())
  const entries: ZipEntry[] = []
  let offset = 0

  for (const file of files) {
    const nameBytes = encoder.encode(file.name)
    const entry: ZipEntry = { nameBytes, data: file.data, crc: crc32(file.data), offset, dosTime, dosDate }
    entries.push(entry)
    // Local header (30) + name + payload.
    offset += 30 + nameBytes.length + file.data.length
  }

  const centralSize = entries.reduce((sum, e) => sum + 46 + e.nameBytes.length, 0)
  const totalSize = offset + centralSize + 22
  const buffer = new Uint8Array(totalSize)
  const view = new DataView(buffer.buffer)

  let pos = 0
  for (const entry of entries) {
    view.setUint32(pos, 0x04034b50, true)
    view.setUint16(pos + 4, 20, true) // version needed
    view.setUint16(pos + 6, 0x0800, true) // UTF-8 names
    view.setUint16(pos + 8, 0, true) // STORE
    view.setUint16(pos + 10, entry.dosTime, true)
    view.setUint16(pos + 12, entry.dosDate, true)
    view.setUint32(pos + 14, entry.crc, true)
    view.setUint32(pos + 18, entry.data.length, true)
    view.setUint32(pos + 22, entry.data.length, true)
    view.setUint16(pos + 26, entry.nameBytes.length, true)
    view.setUint16(pos + 28, 0, true)
    buffer.set(entry.nameBytes, pos + 30)
    pos += 30 + entry.nameBytes.length
    buffer.set(entry.data, pos)
    pos += entry.data.length
  }

  const centralStart = pos
  for (const entry of entries) {
    view.setUint32(pos, 0x02014b50, true)
    view.setUint16(pos + 4, 20, true) // version made by
    view.setUint16(pos + 6, 20, true) // version needed
    view.setUint16(pos + 8, 0x0800, true)
    view.setUint16(pos + 10, 0, true)
    view.setUint16(pos + 12, entry.dosTime, true)
    view.setUint16(pos + 14, entry.dosDate, true)
    view.setUint32(pos + 16, entry.crc, true)
    view.setUint32(pos + 20, entry.data.length, true)
    view.setUint32(pos + 24, entry.data.length, true)
    view.setUint16(pos + 28, entry.nameBytes.length, true)
    // Extra, comment, disk number start, internal/external attrs are zeroed by
    // Uint8Array initialization. The local-header offset belongs at byte 42;
    // writing it at byte 38 corrupts the external-attributes field and leaves
    // every central-directory entry pointing at the first file.
    view.setUint32(pos + 42, entry.offset, true)
    buffer.set(entry.nameBytes, pos + 46)
    pos += 46 + entry.nameBytes.length
  }

  view.setUint32(pos, 0x06054b50, true)
  view.setUint16(pos + 8, entries.length, true)
  view.setUint16(pos + 10, entries.length, true)
  view.setUint32(pos + 12, centralSize, true)
  view.setUint32(pos + 16, centralStart, true)

  return new Blob([buffer], { type: 'application/zip' })
}

// ---------------------------------------------------------------------------

export async function downloadPlaylistZip(
  tracks: Track[],
  callbacks: DownloadCallbacks = {},
  signal?: AbortSignal,
): Promise<DownloadResult> {
  const files: { name: string; data: Uint8Array }[] = []
  const succeeded: DownloadResult['succeeded'] = []
  const failed: DownloadResult['failed'] = []
  const usedNames = new Set<string>()

  for (let index = 0; index < tracks.length; index++) {
    if (signal?.aborted) break
    const track = tracks[index]
    const displayName = baseFileName(track)
    callbacks.onTrackStart?.(index)
    try {
      const { chunks, contentType } = await fetchTrackAudio(track, signal, (received, total) =>
        callbacks.onTrackProgress?.(index, received, total),
      )
      const fileName = `${uniqueName(displayName, usedNames)}${extensionFor(contentType)}`
      const size = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0)
      const data = new Uint8Array(size)
      let cursor = 0
      for (const chunk of chunks) {
        data.set(chunk, cursor)
        cursor += chunk.byteLength
      }
      files.push({ name: fileName, data })
      succeeded.push({ index, fileName })
      callbacks.onTrackDone?.(index)
    } catch (error) {
      if (error instanceof DownloadCancelledError) {
        // Cancellation discards the entire in-memory archive. A partial
        // playlist must never escape to a caller that could save it.
        break
      }
      const reason = error instanceof Error ? error.message : 'download failed'
      failed.push({ fileName: displayName, reason })
      callbacks.onTrackFailed?.(index, reason)
    }
  }

  if (signal?.aborted) throw new DownloadCancelledError()

  if (files.length === 0) {
    throw new Error('None of the tracks could be downloaded.')
  }

  return { blob: buildZip(files), succeeded, failed }
}

export function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
