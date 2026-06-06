<script setup lang="ts" generic="T extends Record<string, any>">
import { VisLine, VisXYContainer, VisAxis, VisArea, VisScatter } from '@unovis/vue'
import { Scatter } from '@unovis/ts'
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
  curve?: 'linear' | 'step' | 'monotone'
}>(), {
  showXAxis: true,
  showYAxis: true,
  showTooltip: true,
  showGridLine: true,
  curve: 'monotone',
})

const x = (_d: T, i: number) => i
const tooltipContent = computed(() => componentToString(props.config, ChartTooltipContent, { labelKey: props.index as string }))
</script>

<template>
  <ChartContainer :config="config" :class="props.class">
    <VisXYContainer :data="data">
      <VisLine
        v-for="category in categories"
        :key="category"
        :x="x"
        :y="(d: T) => d[category]"
        :color="config[category]?.color || 'var(--vis-color-primary)'"
      />
      <VisScatter
        v-for="category in categories"
        :key="`${category}-scatter`"
        :x="x"
        :y="(d: T) => d[category]"
        :color="config[category]?.color || 'var(--vis-color-primary)'"
        :size="6"
        :stroke-width="2"
        stroke-color="#ffffff"
      />
      <VisArea
        v-for="category in categories"
        :key="`${category}-area`"
        :x="x"
        :y="(d: T) => d[category]"
        :color="config[category]?.color || 'var(--vis-color-primary)'"
        :opacity="0.1"
      />
      <VisAxis v-if="showXAxis" type="x" :grid-line="false" />
      <VisAxis v-if="showYAxis" type="y" :grid-line="showGridLine" />
      <ChartTooltip
        v-if="showTooltip"
        :label-formatter="(x: number) => data[x]?.[index]"
        :triggers="{
          [Scatter.selectors.point]: tooltipContent
        }"
      />
    </VisXYContainer>
  </ChartContainer>
</template>
