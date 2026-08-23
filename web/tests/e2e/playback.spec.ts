import { expect, test } from '@playwright/test'

const snapshot = {
  version: 1,
  title: 'Cross-browser test',
  prompt: 'Safari playback test',
  seed: 1,
  tracks: [{
    id: 'dQw4w9WgXcQ',
    name: 'Never Gonna Give You Up',
    artists: ['Rick Astley'],
    year: 1987,
    albumArt: 'https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg',
  }, {
    id: '9bZkp7q19f0',
    name: 'Gangnam Style',
    artists: ['PSY'],
    year: 2012,
    albumArt: 'https://i.ytimg.com/vi/9bZkp7q19f0/maxresdefault.jpg',
  }],
}

function sharePath() {
  return `/#v=j${Buffer.from(JSON.stringify(snapshot)).toString('base64url')}`
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const calls = { load: 0, play: 0, pause: 0 }
    let paused = true
    Object.assign(window, { __audelleAudioCalls: calls, __audelleAudioElement: null })
    let mediaSource = ''
    Object.defineProperty(HTMLMediaElement.prototype, 'src', {
      configurable: true,
      get: () => mediaSource,
      set: function (value: string) {
        mediaSource = value
        Object.assign(window, { __audelleAudioElement: this })
      },
    })
    Object.defineProperty(HTMLMediaElement.prototype, 'paused', { configurable: true, get: () => paused })
    Object.defineProperty(HTMLMediaElement.prototype, 'duration', { configurable: true, get: () => 213 })
    HTMLMediaElement.prototype.load = function () { calls.load += 1 }
    HTMLMediaElement.prototype.play = function () {
      calls.play += 1
      paused = false
      this.dispatchEvent(new Event('playing'))
      return Promise.resolve()
    }
    HTMLMediaElement.prototype.pause = function () {
      calls.pause += 1
      paused = true
      this.dispatchEvent(new Event('pause'))
    }
  })
  await page.route('**/api/audio/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'audio/mpeg', body: Buffer.from('test mp3') })
  })
})

test('native playback starts directly from the Play click', async ({ page }) => {
  await page.goto(sharePath())
  const play = page.getByRole('button', { name: 'Play', exact: true })
  await expect(play).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Previous track' })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Next track' })).toBeEnabled()
  expect(await page.evaluate(() => (window as never as { __audelleAudioCalls: { play: number } }).__audelleAudioCalls.play)).toBe(0)

  await play.click()
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as never as { __audelleAudioCalls: { play: number } }).__audelleAudioCalls.play)).toBe(1)
  expect(await page.evaluate(() => (window as never as { __audelleAudioElement: HTMLMediaElement }).__audelleAudioElement.src)).toContain('/api/audio/dQw4w9WgXcQ')
})

test('Next preserves active playback without requiring two more taps', async ({ page }) => {
  await page.goto(sharePath())
  await page.getByRole('button', { name: 'Play', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Next track' }).click()

  await expect.poll(() => page.evaluate(
    () => (window as never as { __audelleAudioElement: HTMLMediaElement }).__audelleAudioElement.src,
  )).toContain('/api/audio/9bZkp7q19f0')
  await expect.poll(() => page.evaluate(
    () => (window as never as { __audelleAudioCalls: { play: number } }).__audelleAudioCalls.play,
  )).toBe(2)
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
  expect(await page.evaluate(
    () => (window as never as { __audelleAudioElement: HTMLMediaElement }).__audelleAudioElement.src,
  )).toContain('/api/audio/9bZkp7q19f0')
})

test('a media error leaves Play enabled for a user retry', async ({ page }) => {
  await page.goto(sharePath())
  const play = page.getByRole('button', { name: 'Play', exact: true })
  await expect(play).toBeEnabled()

  await page.evaluate(() => {
    const audio = (window as never as { __audelleAudioElement: HTMLMediaElement }).__audelleAudioElement
    audio.dispatchEvent(new Event('error'))
  })
  await expect(page.getByRole('status')).toContainText('Tap Play to retry')
  await expect(play).toBeEnabled()

  await play.click()
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as never as { __audelleAudioCalls: { play: number } }).__audelleAudioCalls.play)).toBe(1)
})

for (const viewport of [
  { name: 'compact phone', width: 320, height: 568 },
  { name: 'standard phone', width: 390, height: 844 },
  { name: 'large phone', width: 430, height: 932 },
]) {
  test(`mobile artwork is contained without overflow on a ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await page.goto(sharePath())

    const artwork = page.locator('[style*="background-image"]').first()
    await expect(artwork).toHaveCSS('background-size', 'contain')
    await expect(artwork).toHaveCSS('background-position', '50% 50%')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(viewport.width)
  })
}
