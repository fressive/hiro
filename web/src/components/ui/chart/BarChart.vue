<script setup lang="ts" generic="T extends Record<string, any>">
import { VisStackedBar, VisXYContainer, VisAxis } from '@unovis/vue'
import { StackedBar } from '@unovis/ts'
import { type HTMLAttributes, computed } from 'vue'
import { ChartContainer, ChartTooltipContent, ChartTooltip, componentToString } from '.'
import { type ChartConfig } from '.'

const props = withDefaults(defineProps<{
  data: T[]
  index: keyof T
  categories: string[]
  config: ChartConfig
  class?: HTMLAttributes['class']
  showXAxis?: boolean
  showYAxis?: boolean
  showTooltip?: boolean
  showGridLine?: boolean
}>(), {
  showXAxis: true,
  showYAxis: true,
  showTooltip: true,
  showGridLine: true,
})

const x = (_d: T, i: number) => i
const y = props.categories.map(c => (d: T) => d[c])
const color = props.categories.map(c => props.config[c]?.color || 'var(--vis-color-primary)')
const tooltipContent = computed(() => componentToString(props.config, ChartTooltipContent, { labelKey: props.index as string }))
</script>

<template>
  <ChartContainer :config="config" :class="props.class">
    <VisXYContainer :data="data">
      <VisStackedBar
        :x="x"
        :y="y"
        :color="color"
        :rounded-corners="4"
        :bar-padding="0.1"
      />
      <VisAxis v-if="showXAxis" type="x" :grid-line="false" />
      <VisAxis v-if="showYAxis" type="y" :grid-line="showGridLine" />
      <ChartTooltip
        v-if="showTooltip"
        :label-formatter="(x: number) => data[x]?.[index]"
        :triggers="{ [StackedBar.selectors.bar]: tooltipContent }"
      />
    </VisXYContainer>
  </ChartContainer>
</template>
