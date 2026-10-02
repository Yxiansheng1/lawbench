// 极简的可订阅状态（界面插件自己的状态，不进 DSH 的 store）。组件用 useStore 取片段。
import { useSyncExternalStore } from 'react'

export interface Store<T> {
  get(): T
  set(next: T | ((prev: T) => T)): void
  subscribe(fn: () => void): () => void
}

export function createStore<T>(initial: T): Store<T> {
  let state = initial
  const subs = new Set<() => void>()
  return {
    get: () => state,
    set(next) {
      const v = typeof next === 'function' ? (next as (p: T) => T)(state) : next
      if (Object.is(v, state)) return
      state = v
      for (const fn of [...subs]) fn()
    },
    subscribe(fn) { subs.add(fn); return () => { subs.delete(fn) } },
  }
}

export function useStore<T, S>(store: Store<T>, select: (s: T) => S): S {
  return useSyncExternalStore(store.subscribe, () => select(store.get()), () => select(store.get()))
}
