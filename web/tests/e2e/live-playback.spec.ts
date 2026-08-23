import { expect, test } from '@playwright/test'

const liveUrl = process.env.AUDELLE_LIVE_URL
const sharedPlaylist =
  '#v=jeyJ2ZXJzaW9uIjoxLCJ0aXRsZSI6IkNyb3NzLWJyb3dzZXIgdGVzdCIsInByb21wdCI6IlNhZmFyaSBwbGF5YmFjayB0ZXN0Iiwic2VlZCI6MSwidHJhY2tzIjpbeyJpZCI6ImRRdzR3OVdnWGNRIiwibmFtZSI6Ik5ldmVyIEdvbm5hIEdpdmUgWW91IFVwIiwiYXJ0aXN0cyI6WyJSaWNrIEFzdGxleSJdLCJ5ZWFyIjoxOTg3LCJhbGJ1bUFydCI6Imh0dHBzOi8vaS55dGltZy5jb20vdmkvZFF3NHc5V2dYY1EvbWF4cmVzZGVmYXVsdC5qcGcifV19'

test('live MP3 playback advances in the browser', async ({ page }) => {
  test.skip(!liveUrl, 'Runs only against an explicitly selected live environment')

  const audioResponse = page.waitForResponse(
    (response) => response.url().includes('/api/audio/dQw4w9WgXcQ'),
    { timeout: 90_000 },
  )

  await page.goto(`/${sharedPlaylist}`)
  await page.getByRole('button', { name: 'Play', exact: true }).click()

  const response = await audioResponse
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toContain('audio/mpeg')
  expect(response.headers()['content-disposition']).toContain('inline')
  await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible({ timeout: 90_000 })
  const elapsedTime = page.getByLabel('Seek within track').locator('xpath=preceding-sibling::span[1]')
  await expect
    .poll(async () => elapsedTime.textContent(), { timeout: 90_000 })
    .not.toBe('0:00')
})
