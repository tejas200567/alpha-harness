/** SuperAlpha: diversity-checked selection preview, then a real SUPER submission. */

import type { components } from '@/api/generated'
import { http } from '@/api/http'

type Schemas = components['schemas']

export type SuperAlphaPreview = Schemas['SuperAlphaPreview']

export interface SuperAlphaRequest {
  region: string
  delay: number
  universe: string
  neutralization: string
  decay: number
  truncation: number
  selectionName: string
  comboName: string
  turnoverMax?: number
  sharpeMin?: number
}

//: Matches the real backend dict keys in tools/superalpha.py -- low_turnover_capacity and
//: low_prod_correlation are verified real, read from this account's own 42 existing
//: SuperAlphas; high_sharpe and low_ops are unverified presets.
export const SELECTION_PRESETS = [
  { value: 'low_turnover_capacity', label: 'Low Turnover / Capacity (verified)' },
  { value: 'low_prod_correlation', label: 'Low Production Correlation (verified)' },
  { value: 'high_sharpe', label: 'High Sharpe (unverified)' },
  { value: 'low_ops', label: 'Low Operator Count (unverified)' },
] as const

//: "decorr" is verified real -- the exact combo code on all 42 of this account's existing
//: SuperAlphas.
export const COMBO_PRESETS = [
  { value: 'decorr', label: 'Decorrelation Weighted (verified)' },
  { value: 'equal', label: 'Equal Weight' },
] as const

const B = '/api/tools/superalpha'

export const superalpha = {
  preview: (body: SuperAlphaRequest) => http.post<SuperAlphaPreview>(`${B}/preview`, body),
  addTask: (body: SuperAlphaRequest) => http.post<Schemas['AddedTask']>(`${B}/tasks`, body),
}
