import { createRouter, createWebHistory } from 'vue-router'

import AppPage from '@/pages/AppPage.vue'
import SessionPage from '@/pages/SessionPage.vue'
import InstallmentPage from '@/pages/InstallmentPage.vue'
import LoginPage from '@/pages/LoginPage.vue'
import LLMPage from '@/pages/LLMPage.vue'
import RAGPage from '@/pages/RAGPage.vue'
import MCPPage from '@/pages/MCPPage.vue'
import APITokenPage from '@/pages/APITokenPage.vue'
import { apiFetch } from '@/lib/api'

type InstallationStatus = {
  installed: boolean
}

let installationStatusPromise: Promise<InstallationStatus> | null = null

async function getInstallationStatus() {
  if (!installationStatusPromise) {
    installationStatusPromise = apiFetch('/api/v1/health')
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Failed to fetch installation status: ${response.status}`)
        }

        return response.json() as Promise<InstallationStatus>
      })
      .catch(() => ({ installed: false }))
  }

  return installationStatusPromise
}


export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/app',
    },
    {
      path: '/login',
      name: 'login',
      component: LoginPage,
    },
    {
      path: '/installment',
      name: 'installment',
      component: InstallmentPage,
    },
    {
      path: '/app',
      name: 'app',
      component: AppPage,
    },
    {
      path: '/sessions',
      name: 'sessions',
      component: SessionPage,
    },
    {
      path: '/llm',
      name: 'llm',
      component: LLMPage,
    },
    {
      path: '/rag',
      name: 'rag',
      component: RAGPage,
    },
    {
      path: '/mcp',
      name: 'mcp',
      component: MCPPage,
    },
    {
      path: '/tokens',
      name: 'tokens',
      component: APITokenPage,
    },
  ],
})

router.beforeEach(async (to) => {
  const { installed } = await getInstallationStatus()

  if (!installed && to.name !== 'installment')
    return { name: 'installment' }

  if (installed && to.name === 'installment')
    return { name: 'app' }

  return true
})

