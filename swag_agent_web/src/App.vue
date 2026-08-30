<script setup>
import { currentTheme, applyTheme } from './theme'

applyTheme(currentTheme())
</script>

<template>
  <router-view />
</template>
