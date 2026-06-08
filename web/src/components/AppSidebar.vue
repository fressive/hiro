<script setup lang="ts">
import {
  LayoutDashboard,
  Bot,
  Database,
  Blocks,
  Key,
  User,
  ChevronUp,
  LogOut,
  Moon,
  Sun,
  MessageCircle,
} from '@lucide/vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useDark, useToggle } from '@vueuse/core'

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'

const router = useRouter()
const route = useRoute()
const isDark = useDark()
const toggleDark = useToggle(isDark)

const items = [
  {
    title: 'Dashboard',
    url: '/app',
    icon: LayoutDashboard,
  },
  {
    title: 'Sessions',
    url: '/sessions',
    icon: MessageCircle,
  },
  {
    title: 'LLM',
    url: '/llm',
    icon: Bot,
  },
  {
    title: 'RAG',
    url: '/rag',
    icon: Database,
  },
  {
    title: 'MCP',
    url: '/mcp',
    icon: Blocks,
  },
  {
    title: 'API Tokens',
    url: '/tokens',
    icon: Key,
  },
]

const handleLogout = () => {
  localStorage.removeItem('HIRO_ACCESS_TOKEN')
  router.push('/login')
}
</script>

<template>
  <Sidebar collapsible="icon">
    <SidebarHeader class="h-16 border-b px-4">
      <div class="flex items-center gap-2 font-bold text-xl overflow-hidden truncate">
        <span class="group-data-[collapsible=icon]:hidden">HIRO</span>
      </div>
    </SidebarHeader>

    <SidebarContent>
      <SidebarGroup>
        <SidebarGroupLabel>Application</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-for="item in items" :key="item.title">
              <SidebarMenuButton
                v-if="item.url"
                as-child
                :is-active="route.path === item.url"
              >
                <RouterLink :to="item.url">
                  <component :is="item.icon" />
                  <span>{{ item.title }}</span>
                </RouterLink>
              </SidebarMenuButton>
              <SidebarMenuButton v-else disabled>
                <component :is="item.icon" />
                <span>{{ item.title }}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>

    <SidebarFooter>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton @click="toggleDark()">
            <Sun v-if="isDark" />
            <Moon v-else />
            <span>{{ isDark ? 'Light' : 'Dark' }} Mode</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton size="lg" class="group-data-[collapsible=icon]:hidden">
            <User />
            <div class="flex flex-col gap-0.5 leading-none">
              <span class="font-semibold">Admin</span>
              <span class="text-xs text-muted-foreground">admin@example.com</span>
            </div>
            <ChevronUp class="ml-auto" />
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton @click="handleLogout" class="text-destructive hover:text-destructive hover:bg-destructive/10">
            <LogOut />
            <span>Logout</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarFooter>
  </Sidebar>
</template>
