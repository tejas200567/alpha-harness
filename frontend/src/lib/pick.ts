/**
 * Picking on another screen for a lab, then going back to it: while `active`, that screen turns
 * into a picker and Done leaves the choice in `result` for the lab that started it to take.
 * Kept in sessionStorage, so a reload in the middle of a pick keeps it.
 */

import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { Scope } from '@/api/types'

export interface PickResult<From> {
  scope: Scope
  ids: string[]
  from: From
}

interface Pick<From> {
  active: boolean
  scope: Scope | null
  ids: string[]
  from: From
  result: PickResult<From> | null
  start: (scope: Scope, ids: string[], from: From) => void
  finish: () => void
  cancel: () => void
  /**
   * Moves the pick to `scope`. What was picked belongs to a region and delay, so only a
   * universe change keeps it.
   */
  follow: (scope: Scope) => void
  /** The finished pick, once, and only for the lab that started it. */
  take: (from: From) => PickResult<From> | null
}

/** `first` also stands in for a pick kept from before picks named their lab. */
export function createPick<From extends string>(name: string, first: From) {
  return create<Pick<From>>()(
    persist(
      (set, get) => ({
        active: false,
        scope: null,
        ids: [],
        from: first,
        result: null,
        start: (scope, ids, from) => set({ active: true, scope, ids, from, result: null }),
        finish: () => {
          const { scope, ids, from } = get()
          set({
            active: false,
            scope: null,
            ids: [],
            result: scope ? { scope, ids, from } : null,
          })
        },
        cancel: () => set({ active: false, scope: null, ids: [], result: null }),
        follow: (scope) => {
          const { scope: current, ids } = get()
          const moved = !current || current.region !== scope.region || current.delay !== scope.delay
          set({ scope, ids: moved ? [] : ids })
        },
        take: (from) => {
          const result = get().result
          if (!result || (result.from ?? first) !== from) return null
          set({ result: null })
          return result
        },
      }),
      { name, storage: createJSONStorage(() => sessionStorage) },
    ),
  )
}
