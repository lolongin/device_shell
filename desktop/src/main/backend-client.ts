export interface BackendRuntime {
  apiBaseUrl: string
  token: string
  apiVersion?: number
}

export interface BackendResponse {
  status: number
  body: string
}

export async function fetchBackend(
  runtime: BackendRuntime,
  pathName: string,
  method = 'GET',
  body?: string,
): Promise<BackendResponse> {
  const response = await fetch(`${runtime.apiBaseUrl}${pathName}`, {
    method,
    headers: {
      Authorization: `Bearer ${runtime.token}`,
      'Content-Type': 'application/json',
    },
    body: method === 'GET' ? undefined : body,
  })
  return { status: response.status, body: await response.text() }
}

export function backendError(response: BackendResponse): Error {
  let message = response.body || `Backend request failed (${response.status})`
  try {
    const payload = JSON.parse(response.body) as { detail?: string; error?: { message?: string } }
    message = payload.error?.message || payload.detail || message
  } catch {
    // Keep the backend's non-JSON response.
  }
  return new Error(message)
}
