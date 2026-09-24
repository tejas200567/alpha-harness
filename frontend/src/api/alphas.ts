/**
 * The alpha pool on BRAIN. Osmosis allocation only, for now -- everything else on this
 * router (page/check/correlations/properties) is used through other screens directly.
 */

import type { components } from './generated'
import { http } from './http'

type Schemas = components['schemas']

export type OsmosisScopeCoverage = Schemas['OsmosisScopeCoverage']
export type OsmosisCoverageResult = Schemas['OsmosisCoverageResult']
export type OsmosisScopeAlpha = Schemas['OsmosisScopeAlpha']
export type AlphaInfo = Schemas['AlphaInfo']

const B = '/api/alphas'

export const alphas = {
  osmosisCoverage: (maxAlphas = 500) =>
    http.get<OsmosisCoverageResult>(`${B}/osmosis/coverage?max_alphas=${maxAlphas}`),
  osmosisScopeAlphas: (region: string, delay: number, maxAlphas = 200) =>
    http.get<OsmosisScopeAlpha[]>(
      `${B}/osmosis/scope-alphas?region=${encodeURIComponent(region)}&delay=${delay}&max_alphas=${maxAlphas}`,
    ),
  setOsmosisPoints: (alphaId: string, points: number) =>
    http.patch<AlphaInfo>(`${B}/${encodeURIComponent(alphaId)}/osmosis-points`, { points }),
}
