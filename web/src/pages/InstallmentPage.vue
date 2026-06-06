<script setup lang="ts">
import { vAutoAnimate } from '@formkit/auto-animate/vue'
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { ref } from 'vue'
import { Check, Loader2, AlertCircle, XCircle } from '@lucide/vue'
import * as z from 'zod'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { 
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Stepper,
  StepperItem,
  StepperTrigger,
  StepperIndicator,
  StepperSeparator,
} from '@/components/ui/stepper'
import { apiFetch } from '@/lib/api'
const currentStep = ref(1)
const isChecking = ref(false)
const dbError = ref('')
const installError = ref('')
const isInstalling = ref(false)

const steps = [
  { number: 1, title: 'Database setup' },
  { number: 2, title: 'Environment check' },
  { number: 3, title: 'Admin account' },
]

// Simple state for form data
const databaseDsn = ref('')

// Environment check state
interface SystemCheckItem {
  name: string
  exists: boolean
  message?: string
}

const systemCheckItems = ref<SystemCheckItem[]>([])
const isSystemChecking = ref(false)
const systemCheckSuccess = ref(false)

const runSystemCheck = async () => {
  isSystemChecking.value = true
  try {
    const response = await apiFetch('/api/v1/install/check-system')
    if (!response.ok) throw new Error('Failed to check system requirements')
    const data = await response.json()
    systemCheckItems.value = data.items
    systemCheckSuccess.value = data.success
  } catch (error) {
    console.error(error)
    systemCheckSuccess.value = false
  } finally {
    isSystemChecking.value = false
  }
}

// Database setup - check connection and navigate
const handleNextStep0 = async () => {
  if (databaseDsn.value.length < 10) return

  isChecking.value = true
  dbError.value = ''

  try {
    const response = await apiFetch('/api/v1/install/check-db', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ database_url: databaseDsn.value }),
    })

    if (!response.ok) {
        throw new Error('Network response was not ok')
    }

    const data = await response.json()
    if (data.success) {
      currentStep.value = 1
      runSystemCheck()
    } else {
      dbError.value = data.message || 'Failed to connect to the database.'
    }
  } catch (error) {
    dbError.value = 'An error occurred while connecting to the database. Make sure the backend is running.'
    console.error(error)
  } finally {
    isChecking.value = false
  }
}

// Admin account form
const adminFormSchema = toTypedSchema(z.object({
  name: z.string().min(2, 'Name must be at least 2 characters').max(50),
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters').max(72, 'Password must be at most 72 characters'),
  confirm: z.string().min(8).max(72),
}).refine((data) => data.password === data.confirm, {
  message: "Passwords don't match",
  path: ["confirm"],
}))

const { handleSubmit: handleAdminSubmit } = useForm({
  validationSchema: adminFormSchema,
})

const onAdminSubmit = handleAdminSubmit(async (values) => {
  isInstalling.value = true
  installError.value = ''
  
  try {
    const response = await apiFetch('/api/v1/install', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        database_url: databaseDsn.value,
        admin_username: values.name,
        admin_email: values.email,
        admin_password: values.password,
      }),
    })

    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.detail || 'Installation failed')
    }

    const waitForHealth = async () => {
      const maxAttempts = 12
      const delayMs = 1500

      for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        try {
          const health = await apiFetch('/api/v1/health')
          if (health.ok) {
            const data = await health.json().catch(() => null)
            if (data?.installed) return
          }
        } catch (error) {
          console.error(error)
        }

        await new Promise((resolve) => setTimeout(resolve, delayMs))
      }

      throw new Error('Server is still restarting. Please refresh in a moment.')
    }

    await waitForHealth()
    window.location.href = '/login'
  } catch (error: any) {
    installError.value = error.message || 'An error occurred during installation.'
    console.error(error)
  } finally {
    isInstalling.value = false
  }
})
</script>

<template>
  <main class="min-h-screen bg-background px-6 py-10">
    <Card class="mx-auto w-full max-w-5xl">
      <CardHeader class="border-b">
        <CardTitle class="text-2xl">Install</CardTitle>
      </CardHeader>

      <CardContent class="space-y-8 p-6 sm:p-8">
        <div class="flex flex-col gap-6">
          <Stepper v-model="currentStep" class="w-full gap-4">
            <StepperItem v-for="(step, index) in steps" :key="index" :step="index" :value="index" class="flex-1">
              <StepperTrigger class="!p-0 group w-full cursor-default" disabled>
                <div class="flex flex-col items-center gap-2">
                  <StepperIndicator class="border-2 border-primary text-primary data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=completed]:bg-primary data-[state=completed]:text-primary-foreground">
                    <Check v-if="currentStep > index" class="h-4 w-4" />
                    <span v-else>{{ step.number }}</span>
                  </StepperIndicator>
                  <span class="text-sm font-medium text-foreground">{{ step.title }}</span>
                </div>
              </StepperTrigger>
              <StepperSeparator v-if="index < steps.length - 1" class="!h-1 !bg-primary group-data-[state=completed]:!bg-primary flex-1 mx-2" />
            </StepperItem>
          </Stepper>

          <div class="space-y-6">
            <section v-if="currentStep === 0" class="space-y-5">
              <div class="space-y-6">
                <div class="space-y-2">
                  <Label for="db-dsn">Database DSN</Label>
                  <Input 
                    id="db-dsn" 
                    v-model="databaseDsn"
                    type="text"
                    placeholder="postgresql://user:password@localhost:5432/hiro"
                    :disabled="isChecking"
                  />
                  <p class="text-sm text-muted-foreground">
                    Enter your database connection string. Example formats:
                    <br />PostgreSQL: <code class="text-xs bg-muted px-1 py-0.5 rounded">postgresql://user:password@host:5432/database</code>
                    <br />SQLite: <code class="text-xs bg-muted px-1 py-0.5 rounded">sqlite:///./hiro.db</code>
                  </p>
                  <p v-if="dbError" class="text-sm font-medium text-destructive">
                    {{ dbError }}
                  </p>
                </div>

                <div class="flex justify-end gap-3">
                  <Button variant="outline" disabled>
                    Back
                  </Button>
                  <Button type="button" @click="handleNextStep0" :disabled="databaseDsn.length < 10 || isChecking">
                    <Loader2 v-if="isChecking" class="mr-2 h-4 w-4 animate-spin" />
                    Next
                  </Button>
                </div>
              </div>
            </section>

            <section v-else-if="currentStep === 1" class="space-y-5">
              <div class="space-y-4">
                <div v-if="isSystemChecking" class="flex flex-col items-center justify-center py-10 space-y-4">
                  <Loader2 class="h-8 w-8 animate-spin text-primary" />
                  <p class="text-sm text-muted-foreground">Checking system requirements...</p>
                </div>
                
                <div v-else class="space-y-4">
                  <div class="grid gap-4">
                    <div v-for="item in systemCheckItems" :key="item.name" 
                      class="flex items-center justify-between p-4 rounded-lg border border-border bg-card"
                    >
                      <div class="flex items-center gap-3">
                        <div :class="item.exists ? 'text-green-500' : 'text-destructive'">
                          <Check v-if="item.exists" class="h-5 w-5" />
                          <XCircle v-else class="h-5 w-5" />
                        </div>
                        <div>
                          <p class="font-medium capitalize">{{ item.name }}</p>
                          <p class="text-xs text-muted-foreground truncate max-w-[300px]">{{ item.message }}</p>
                        </div>
                      </div>
                      <div v-if="item.exists" class="text-xs font-medium px-2 py-1 rounded bg-green-500/10 text-green-500">
                        Installed
                      </div>
                      <div v-else class="text-xs font-medium px-2 py-1 rounded bg-destructive/10 text-destructive">
                        Missing
                      </div>
                    </div>
                  </div>

                  <div v-if="!systemCheckSuccess" class="flex items-start gap-3 p-4 rounded-lg bg-destructive/10 text-destructive text-sm">
                    <AlertCircle class="h-5 w-5 shrink-0" />
                    <p>Some required programs are missing. Please install them on your server and click "Retry" before proceeding.</p>
                  </div>
                </div>
              </div>

              <div class="flex items-center justify-between gap-3">
                <Button type="button" variant="outline" @click="currentStep = 0" :disabled="isSystemChecking">
                  Back
                </Button>
                <div class="flex gap-3">
                  <Button type="button" variant="secondary" @click="runSystemCheck" :disabled="isSystemChecking">
                    <Loader2 v-if="isSystemChecking" class="mr-2 h-4 w-4 animate-spin" />
                    Retry
                  </Button>
                  <Button type="button" @click="currentStep = 2" :disabled="isSystemChecking || !systemCheckSuccess">
                    Next
                  </Button>
                </div>
              </div>
            </section>

            <section v-else class="space-y-5">
              <form @submit.prevent="onAdminSubmit" class="space-y-6">
                <FormField v-slot="{ componentField }" name="name">
                  <FormItem v-auto-animate>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input type="text" placeholder="Admin" v-bind="componentField" :disabled="isInstalling" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                </FormField>

                <FormField v-slot="{ componentField }" name="email">
                  <FormItem v-auto-animate>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input type="email" placeholder="admin@example.com" v-bind="componentField" :disabled="isInstalling" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                </FormField>

                <FormField v-slot="{ componentField }" name="password">
                  <FormItem v-auto-animate>
                    <FormLabel>Password</FormLabel>
                    <FormControl>
                      <Input type="password" placeholder="••••••••" v-bind="componentField" :disabled="isInstalling" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                </FormField>

                <FormField v-slot="{ componentField }" name="confirm">
                  <FormItem v-auto-animate>
                    <FormLabel>Confirm password</FormLabel>
                    <FormControl>
                      <Input type="password" placeholder="••••••••" v-bind="componentField" :disabled="isInstalling" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                </FormField>

                <p v-if="installError" class="text-sm font-medium text-destructive">
                  {{ installError }}
                </p>

                <div class="flex items-center justify-between gap-3">
                  <Button type="button" variant="outline" @click="currentStep = 1" :disabled="isInstalling">
                    Back
                  </Button>
                  <Button type="submit" :disabled="isInstalling">
                    <Loader2 v-if="isInstalling" class="mr-2 h-4 w-4 animate-spin" />
                    Finish
                  </Button>
                </div>
              </form>
            </section>
          </div>
        </div>
      </CardContent>
    </Card>
  </main>
</template>
