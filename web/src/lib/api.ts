export const API_UNAVAILABLE_EVENT = 'hiro:api-unavailable'
export const API_UNAVAILABLE_MESSAGE = 'Unable to connect server'

export const getApiBaseUrl = () => {
  if (typeof window === 'undefined') return ''
  return localStorage.getItem('HIRO_DEBUG_API_URL') || ''
}

export const setApiBaseUrl = (url: string) => {
  if (url) {
    localStorage.setItem('HIRO_DEBUG_API_URL', url)
  } else {
    localStorage.removeItem('HIRO_DEBUG_API_URL')
  }
}

export const apiFetch = (path: string, options?: RequestInit) => {
  const baseUrl = getApiBaseUrl()
  const url = baseUrl 
    ? `${baseUrl.replace(/\/$/, '')}${path.startsWith('/') ? path : `/${path}`}` 
    : path
  
  const headers = new Headers(options?.headers)
  const token = localStorage.getItem('HIRO_ACCESS_TOKEN')
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  return fetch(url, {
    ...options,
    headers,
  })
    .then((response) => {
      if (response.status === 401 && typeof window !== 'undefined') {
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
      }

      return response
    })
    .catch((error) => {
      const isAbortError = error instanceof DOMException && error.name === 'AbortError'

      if (!isAbortError && typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent(API_UNAVAILABLE_EVENT, {
            detail: { message: API_UNAVAILABLE_MESSAGE },
          }),
        )
      }

      throw isAbortError ? error : new Error(API_UNAVAILABLE_MESSAGE)
    })
}
