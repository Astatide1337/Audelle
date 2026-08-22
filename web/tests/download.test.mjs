import assert from 'node:assert/strict'
import test from 'node:test'

import { buildZip, DownloadCancelledError, downloadPlaylistZip } from '../src/lib/download.ts'

const decoder = new TextDecoder()

async function readStoredZip(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer())
  const view = new DataView(bytes.buffer)
  const entries = []
  for (let offset = 0; offset <= bytes.length - 46; offset += 1) {
    if (view.getUint32(offset, true) !== 0x02014b50) continue
    const nameLength = view.getUint16(offset + 28, true)
    const size = view.getUint32(offset + 24, true)
    const localOffset = view.getUint32(offset + 42, true)
    assert.equal(view.getUint32(localOffset, true), 0x04034b50)
    const localNameLength = view.getUint16(localOffset + 26, true)
    const localExtraLength = view.getUint16(localOffset + 28, true)
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength
    entries.push({
      name: decoder.decode(bytes.slice(offset + 46, offset + 46 + nameLength)),
      data: decoder.decode(bytes.slice(dataOffset, dataOffset + size)),
      localOffset,
    })
  }
  return entries
}

test('buildZip writes distinct central-directory pointers for every file', async () => {
  const encoder = new TextEncoder()
  const entries = await readStoredZip(buildZip([
    { name: 'one.txt', data: encoder.encode('first') },
    { name: 'two.txt', data: encoder.encode('second') },
  ]))

  assert.deepEqual(entries.map(({ name, data }) => ({ name, data })), [
    { name: 'one.txt', data: 'first' },
    { name: 'two.txt', data: 'second' },
  ])
  assert.notEqual(entries[0].localOffset, entries[1].localOffset)
})

test('downloadPlaylistZip preserves response bytes and media extensions', async (context) => {
  const originalFetch = globalThis.fetch
  context.after(() => { globalThis.fetch = originalFetch })
  globalThis.fetch = async (url) => {
    const webm = String(url).includes('track-one')
    return new Response(webm ? 'opus-bytes' : 'aac-bytes', {
      headers: { 'Content-Type': webm ? 'audio/webm' : 'audio/mp4' },
    })
  }
  const tracks = [
    { id: 'track-one01', name: 'Signal', artists: ['Artist'], year: 2026, popularity: 1, watch_url: '', album_art: null },
    { id: 'track-two02', name: 'Signal', artists: ['Artist'], year: 2026, popularity: 1, watch_url: '', album_art: null },
  ]

  const result = await downloadPlaylistZip(tracks)
  const entries = await readStoredZip(result.blob)

  assert.deepEqual(entries.map(({ name, data }) => ({ name, data })), [
    { name: 'Artist — Signal.webm', data: 'opus-bytes' },
    { name: 'Artist — Signal (2).m4a', data: 'aac-bytes' },
  ])
  assert.equal(result.failed.length, 0)
})

test('downloadPlaylistZip discards completed tracks when cancelled', async (context) => {
  const originalFetch = globalThis.fetch
  context.after(() => { globalThis.fetch = originalFetch })
  globalThis.fetch = async () => new Response('audio-bytes', {
    headers: { 'Content-Type': 'audio/webm' },
  })
  const tracks = [
    { id: 'track-one01', name: 'Signal', artists: ['Artist'], year: 2026, popularity: 1, watch_url: '', album_art: null },
    { id: 'track-two02', name: 'Afterglow', artists: ['Artist'], year: 2026, popularity: 1, watch_url: '', album_art: null },
  ]
  const controller = new AbortController()

  await assert.rejects(
    downloadPlaylistZip(tracks, { onTrackDone: () => controller.abort() }, controller.signal),
    DownloadCancelledError,
  )
})
