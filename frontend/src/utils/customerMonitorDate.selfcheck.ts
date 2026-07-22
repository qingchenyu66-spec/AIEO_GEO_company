/**
 * ponytail: previous-period range self-check
 * Run: npx --yes tsx src/utils/customerMonitorDate.selfcheck.ts
 */
import {
  workspacePeriodCompareLabel,
  workspacePreviousPeriodRange,
} from './customerMonitorDate'

const week = workspacePreviousPeriodRange('7d', '2026-07-13', '2026-07-19')
if (!week || week.startDate !== '2026-07-06' || week.endDate !== '2026-07-12') {
  throw new Error(`7d prev mismatch: ${JSON.stringify(week)}`)
}

const month = workspacePreviousPeriodRange('month', '2026-07-01', '2026-07-19')
if (!month || month.startDate !== '2026-06-01' || month.endDate !== '2026-06-19') {
  throw new Error(`month prev mismatch: ${JSON.stringify(month)}`)
}

if (workspacePeriodCompareLabel('7d') !== '较上周') {
  throw new Error('label 7d')
}
if (workspacePeriodCompareLabel('month') !== '较上月') {
  throw new Error('label month')
}

console.log('customerMonitorDate.selfcheck ok')
