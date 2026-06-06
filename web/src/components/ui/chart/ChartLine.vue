<script setup lang="ts">
import { VisLine } from "@unovis/vue"
import { type HTMLAttributes, computed } from "vue"
import { useChart } from "."

const props = defineProps<{
  index: string
  class?: HTMLAttributes["class"]
}>()

const { config } = useChart()

const color = computed(() => config.value[props.index]?.color || `var(--vis-color-${props.index})`)
</script>

<template>
  <VisLine
    :x="(_d: any, i: number) => i"
    :y="(d: any) => d[index]"
    :color="color"
    :class="props.class"
  />
</template>
