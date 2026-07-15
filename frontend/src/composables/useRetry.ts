export function wait(ms: number) {
  return new Promise<void>(resolve => window.setTimeout(resolve, ms))
}

/** 4xx (auth/permission/validation) must not be retried — retry only multiplies toast spam. */
export function isNonRetryableHttpError(error: unknown): boolean {
  const status = (error as { response?: { status?: number } } | null)?.response?.status
  return typeof status === 'number' && status >= 400 && status < 500
}

export async function withRetry<T>(loader: () => Promise<T>, retries = 2): Promise<T> {
  let lastError: unknown
  for (let index = 0; index <= retries; index += 1) {
    try {
      return await loader()
    } catch (error) {
      lastError = error
      if (isNonRetryableHttpError(error) || index >= retries) break
      await wait(350 * (index + 1))
    }
  }
  throw lastError
}
