/**
 * Stateless share links.
 *
 * A shared playlist is a full snapshot encoded into the URL fragment, so the
 * server holds nothing: no database row, no account, no token. The fragment
 * never reaches a server anyway — the browser parses it locally.
 *
 * Wire format inside `#v=`:
 *   z<base64url(deflate-raw(json))>   when CompressionStream is available
 *   j<base64url(utf8(json))>          fallback for older browsers
 */

export const SNAPSHOT_VERSION = 1

/** Keep links comfortably below every browser's practical fragment limit. */
const MAX_ENCODED_LENGTH = 16_384
const MAX_TRACKS = 50
const MAX_TITLE_LENGTH = 200
const MAX_PROMPT_LENGTH = 500
const MAX_ARTISTS = 5
const MAX_TEXT_LENGTH = 200
const MAX_ALBUM_ART_LENGTH = 500

export interface ShareTrack {
  id: string
  name: string
  artists: string[]
  year: number
  albumArt?: string
}

export interface PlaylistSnapshot {
  version: typeof SNAPSHOT_VERSION
  title: string
  prompt: string
  seed: number
  tracks: ShareTrack[]
}

export class ShareLinkError extends Error {}

const VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/

function toBase64Url(bytes: Uint8Array): string {
  let binary = ''
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fromBase64Url(encoded: string): Uint8Array<ArrayBuffer> {
  const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

async function deflate(bytes: Uint8Array<ArrayBuffer>): Promise<Uint8Array | null> {
  if (typeof CompressionStream !== 'function') return null
  try {
    const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate-raw'))
    return new Uint8Array(await new Response(stream).arrayBuffer())
  } catch {
    return null
  }
}

async function inflate(bytes: Uint8Array<ArrayBuffer>): Promise<Uint8Array<ArrayBuffer> | null> {
  if (typeof DecompressionStream !== 'function') return null
  try {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
    return new Uint8Array(await new Response(stream).arrayBuffer())
  } catch {
    return null
  }
}

function utf8Bytes(text: string): Uint8Array<ArrayBuffer> {
  // TextEncoder returns a view over a plain ArrayBuffer in practice, but its
  // static type is ArrayBufferLike; copy so Blob accepts the buffer.
  const source = new TextEncoder().encode(text)
  const bytes = new Uint8Array(source.length)
  bytes.set(source)
  return bytes
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asIntInRange(value: unknown, min: number, max: number): number | null {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) return null
  return value
}

function validateTrack(raw: unknown): ShareTrack | null {
  if (!isPlainObject(raw)) return null
  if (typeof raw.id !== 'string' || !VIDEO_ID_RE.test(raw.id)) return null
  if (typeof raw.name !== 'string' || raw.name.length === 0 || raw.name.length > MAX_TEXT_LENGTH) return null

  if (!Array.isArray(raw.artists) || raw.artists.length === 0 || raw.artists.length > MAX_ARTISTS) return null
  const artists: string[] = []
  for (const artist of raw.artists) {
    if (typeof artist !== 'string' || artist.length === 0 || artist.length > MAX_TEXT_LENGTH) return null
    artists.push(artist)
  }

  const year = asIntInRange(raw.year, 0, 2100)
  if (year === null) return null

  const track: ShareTrack = { id: raw.id, name: raw.name, artists, year }
  if (raw.albumArt !== undefined) {
    if (typeof raw.albumArt !== 'string' || !raw.albumArt.startsWith('https://') || raw.albumArt.length > MAX_ALBUM_ART_LENGTH) {
      return null
    }
    track.albumArt = raw.albumArt
  }
  return track
}

function validateSnapshot(raw: unknown): PlaylistSnapshot | null {
  if (!isPlainObject(raw)) return null
  if (raw.version !== SNAPSHOT_VERSION) return null
  if (typeof raw.title !== 'string' || raw.title.length > MAX_TITLE_LENGTH) return null
  if (typeof raw.prompt !== 'string' || raw.prompt.length > MAX_PROMPT_LENGTH) return null

  const seed = asIntInRange(raw.seed, 0, Number.MAX_SAFE_INTEGER)
  if (seed === null) return null

  if (!Array.isArray(raw.tracks) || raw.tracks.length === 0 || raw.tracks.length > MAX_TRACKS) return null
  const tracks: ShareTrack[] = []
  const seenIds = new Set<string>()
  for (const item of raw.tracks) {
    const track = validateTrack(item)
    if (!track) return null
    // Duplicate IDs would double-render slides and double-download audio.
    if (seenIds.has(track.id)) continue
    seenIds.add(track.id)
    tracks.push(track)
  }
  if (tracks.length === 0) return null

  return { version: SNAPSHOT_VERSION, title: raw.title, prompt: raw.prompt, seed, tracks }
}

export async function encodePlaylistSnapshot(snapshot: PlaylistSnapshot): Promise<string> {
  const json = utf8Bytes(JSON.stringify(snapshot))
  const deflated = await deflate(json)
  const encoded = deflated ? `z${toBase64Url(deflated)}` : `j${toBase64Url(json)}`
  if (encoded.length > MAX_ENCODED_LENGTH) {
    throw new ShareLinkError('This playlist is too large to share as a link.')
  }
  return encoded
}

export async function decodePlaylistSnapshot(encoded: string): Promise<PlaylistSnapshot | null> {
  if (encoded.length < 2 || encoded.length > MAX_ENCODED_LENGTH) return null
  const format = encoded[0]
  const payload = encoded.slice(1)

  let bytes: Uint8Array<ArrayBuffer>
  try {
    bytes = fromBase64Url(payload)
  } catch {
    return null
  }

  let jsonBytes = bytes
  if (format === 'z') {
    const inflated = await inflate(bytes)
    if (!inflated) return null
    jsonBytes = inflated
  } else if (format !== 'j') {
    return null
  }

  try {
    const raw: unknown = JSON.parse(new TextDecoder().decode(jsonBytes))
    return validateSnapshot(raw)
  } catch {
    return null
  }
}

export function buildShareUrl(snapshot: PlaylistSnapshot): Promise<string> {
  return encodePlaylistSnapshot(snapshot).then((encoded) => `${location.origin}${location.pathname}#v=${encoded}`)
}

/** Clipboard write with a legacy fallback for non-secure contexts. */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const helper = document.createElement('textarea')
      helper.value = text
      helper.setAttribute('readonly', '')
      helper.style.position = 'fixed'
      helper.style.opacity = '0'
      document.body.appendChild(helper)
      helper.select()
      const copied = document.execCommand('copy')
      helper.remove()
      return copied
    } catch {
      return false
    }
  }
}

export async function buildPlaylistShareUrl(
  title: string,
  prompt: string,
  seed: number,
  tracks: { id: string; name: string; artists: string[]; year: number; album_art?: string | null }[],
): Promise<string> {
  return buildShareUrl({
    version: SNAPSHOT_VERSION,
    title,
    prompt,
    seed,
    tracks: tracks.map((track) => ({
      id: track.id,
      name: track.name,
      artists: track.artists,
      year: track.year,
      albumArt: track.album_art ?? undefined,
    })),
  })
}

/** Keep the user's vibe recognizable while keeping titles file-name safe. */
export function playlistTitleFromPrompt(prompt: string): string {
  const normalized = prompt.replace(/\s+/g, ' ').trim()
  return Array.from(normalized || 'Audelle playlist').slice(0, MAX_TITLE_LENGTH).join('')
}
