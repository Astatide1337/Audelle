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
  }],
}

function sharePath() {
  return `/#v=j${Buffer.from(JSON.stringify(snapshot)).toString('base64url')}`
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const calls = { load: 0, play: 0, pause: 0 }
    Object.assign(window, { __audellePlayerCalls: calls })

    class MockPlayer {
      private state = 5
      private readonly events

      constructor(element: HTMLElement, options: { width: string; height: string; events: { onReady: () => void; onStateChange: (event: { data: number }) => void } }) {
        this.events = options.events
        const frame = document.createElement('iframe')
        frame.title = 'Mock YouTube player'
        frame.style.width = `${options.width}px`
        frame.style.height = `${options.height}px`
        element.appendChild(frame)
        setTimeout(() => options.events.onReady(), 0)
      }

      loadVideoById() { calls.load += 1; this.state = 5; this.events.onStateChange({ data: 5 }) }
      playVideo() { calls.play += 1; this.state = 1; this.events.onStateChange({ data: 1 }) }
      pauseVideo() { calls.pause += 1; this.state = 2; this.events.onStateChange({ data: 2 }) }
      getPlayerState() { return this.state }
      getCurrentTime() { return 0 }
      getDuration() { return 213 }
      seekTo() {}
      destroy() {}
    }

    Object.assign(window, { YT: { Player: MockPlayer } })
  })
})

test('playback can start from a click and uses a supported player size', async ({ page }) => {
  await page.goto(sharePath())
  const play = page.getByRole('button', { name: 'Play', exact: true })
  await expect(play).toBeEnabled()

  await expect.poll(() => page.evaluate(() => (window as never as { __audellePlayerCalls: { load: number } }).__audellePlayerCalls.load)).toBe(1)
  expect(await page.evaluate(() => (window as never as { __audellePlayerCalls: { play: number } }).__audellePlayerCalls.play)).toBe(0)

  const frame = page.locator('iframe[title="Mock YouTube player"]')
  await expect(frame).toHaveCSS('width', '200px')
  await expect(frame).toHaveCSS('height', '200px')

  await play.click()
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as never as { __audellePlayerCalls: { play: number } }).__audellePlayerCalls.play)).toBe(1)
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
