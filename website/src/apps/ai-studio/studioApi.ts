// Client for the ai-studio project backend
// (/api/apps/ai-studio/*, src/kiro_crew/apps/builtins/ai_studio/backend/).
//
// Plain same-origin fetch, the issue-radar precedent: a builtin page is served
// by the gateway itself, so the dashboard session cookie authenticates it —
// the scoped app api would add an allowlist check against a list this same
// app declares, buying nothing for its own namespace.
//
// Errors carry the backend's machine-readable `code` where one exists, so a
// caller can branch on "project_not_found" vs "app_disabled" without string
// matching English prose (the backend's error text is not localized; the codes
// are its stable API).

const API = '/api/apps/ai-studio'

export interface StudioProject {
  id: string
  name: string
  description: string
  createdAt: number
}

export interface StudioDoc {
  name: string
  content: string
}

export class StudioApiError extends Error {
  readonly code: string
  readonly status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, {
    credentials: 'same-origin',
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  })
  if (!res.ok) {
    let code = 'request_failed'
    let message = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.code === 'string') code = body.code
      if (typeof body?.error === 'string') message = body.error
    } catch {
      /* non-JSON error body: keep statusText */
    }
    throw new StudioApiError(res.status, code, message)
  }
  return res.json() as Promise<T>
}

export const studioApi = {
  listProjects: () => request<{ projects: StudioProject[] }>('/projects'),
  createProject: (name: string, description: string) =>
    request<{ project: StudioProject }>('/projects', {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    }),
  getProject: (id: string) =>
    request<{ project: StudioProject; docs: StudioDoc[] }>(
      '/projects/' + encodeURIComponent(id),
    ),
  saveDoc: (id: string, name: string, content: string) =>
    request<{ doc: StudioDoc }>(`/projects/${encodeURIComponent(id)}/docs`, {
      method: 'POST',
      body: JSON.stringify({ name, content }),
    }),
}
