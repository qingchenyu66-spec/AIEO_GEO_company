export function wait(ms: number) {
  return new Promise<void>(resolve => window.setTimeout(resolve, ms))
}

export async function withRetry<T>(loader: () => Promise<T>, retries = 2): Promise<T> {
  let lastError: unknown
  for (let index = 0; index <= retries; index += 1) {
    try {
      return await loader()
    } catch (error) {
      lastError = error
      if (index < retries) await wait(350 * (index + 1))
    }
  }
  throw lastError
}
