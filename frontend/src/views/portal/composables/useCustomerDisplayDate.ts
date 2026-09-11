import { computed, inject, type Ref } from 'vue'
import { useAuthStore } from '../../../stores/auth'
import { PreviewCustomerIncludesTodayKey } from '../injectionKeys'
import {
  customerDisplayCutoffDate,
  customerDisplayDateRange,
  customerDisplayPeriodLabel,
  workspaceTrendDateRange,
  type WorkspaceTrendPreset,
} from '../../../utils/customerMonitorDate'

/** 客户门户日期口径：算力自助含今日，托管仍截至昨日。 */
export function useCustomerDisplayDate() {
  const auth = useAuthStore()
  const previewIncludesToday = inject(PreviewCustomerIncludesTodayKey, null as Ref<boolean | null> | null)
  const includesToday = computed(() => {
    if (previewIncludesToday?.value != null) return previewIncludesToday.value
    return Boolean(auth.session?.customer_includes_today)
  })
  const cutoffDate = computed(() => customerDisplayCutoffDate(new Date(), includesToday.value))
  const periodLabel = computed(() => customerDisplayPeriodLabel(includesToday.value))

  function dateRange(lookbackDays = 7) {
    return customerDisplayDateRange(lookbackDays, new Date(), includesToday.value)
  }

  function trendRange(
    preset: WorkspaceTrendPreset,
    customStart?: string,
    customEnd?: string,
  ) {
    return workspaceTrendDateRange(preset, customStart, customEnd, new Date(), includesToday.value)
  }

  return { includesToday, cutoffDate, periodLabel, dateRange, trendRange }
}
