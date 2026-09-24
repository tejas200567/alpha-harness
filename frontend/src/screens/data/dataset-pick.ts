/** Picking datasets in the Data Explorer's Fields filters for a lab. */

import { createPick } from '@/lib/pick'

export type PickFrom = '/labs/search' | '/labs/template' | '/labs/power-pool'

export const useDatasetPick = createPick<PickFrom>('alpha-harness-dataset-pick', '/labs/search')
