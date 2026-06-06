<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { z } from 'zod'
import { Loader2 } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { apiFetch } from '@/lib/api'

const router = useRouter()
const isSubmitting = ref(false)
const loginError = ref('')

const formSchema = toTypedSchema(
  z.object({
    username: z.string().min(1, 'Username is required'),
    password: z.string().min(1, 'Password is required').max(72, 'Password must be at most 72 characters'),
  }),
)

const form = useForm({
  validationSchema: formSchema,
  initialValues: {
    username: '',
    password: '',
  },
})

const onSubmit = form.handleSubmit(async (values) => {
  isSubmitting.value = true
  loginError.value = ''

  try {
    // Note: The current backend implementation expects username/password as query parameters
    const params = new URLSearchParams({
      username: values.username,
      password: values.password,
    })

    const response = await apiFetch(`/api/v1/auth/login?${params.toString()}`, {
      method: 'POST',
    })

    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.detail || 'Login failed')
    }

    const data = await response.json()
    localStorage.setItem('HIRO_ACCESS_TOKEN', data.access_token)
    
    // Redirect to app
    router.push('/app')
  } catch (error: any) {
    loginError.value = error.message || 'An error occurred during login.'
    console.error(error)
  } finally {
    isSubmitting.value = false
  }
})
</script>

<template>
  <main class="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
    <Card class="w-full max-w-md shadow-sm">
      <CardHeader>
        <CardTitle class="text-2xl">Login</CardTitle>
      </CardHeader>

      <CardContent>
        <form @submit="onSubmit" class="space-y-6">
          <FormField v-slot="{ componentField }" name="username">
            <FormItem>
              <FormLabel>Username</FormLabel>
              <FormControl>
                <Input type="text" placeholder="admin" v-bind="componentField" :disabled="isSubmitting" />
              </FormControl>
              <FormMessage />
            </FormItem>
          </FormField>

          <FormField v-slot="{ componentField }" name="password">
            <FormItem>
              <FormLabel>Password</FormLabel>
              <FormControl>
                <Input type="password" placeholder="••••••••" v-bind="componentField" :disabled="isSubmitting" />
              </FormControl>
              <FormMessage />
            </FormItem>
          </FormField>

          <p v-if="loginError" class="text-sm font-medium text-destructive">
            {{ loginError }}
          </p>

          <Button type="submit" class="w-full" :disabled="isSubmitting">
            <Loader2 v-if="isSubmitting" class="mr-2 h-4 w-4 animate-spin" />
            Sign in
          </Button>
        </form>
      </CardContent>
    </Card>
  </main>
</template>
