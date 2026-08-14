import type { Category } from './types'

export interface CategoryNode {
  category: Category
  children: Category[]
}

/**
 * Плоский список категорий превращает в дерево из двух уровней.
 *
 * Сервер отдаёт плоский список намеренно: так его проще кэшировать и фильтровать.
 * Разложить его по родителям — работа на один проход, и делать её лучше здесь,
 * чем повторять в каждом экране.
 */
export function buildTree(categories: Category[]): CategoryNode[] {
  const roots = categories.filter((item) => !item.parent_id)
  const childrenOf = new Map<string, Category[]>()
  for (const item of categories) {
    if (!item.parent_id) continue
    const bucket = childrenOf.get(item.parent_id)
    if (bucket) bucket.push(item)
    else childrenOf.set(item.parent_id, [item])
  }
  return roots.map((category) => ({
    category,
    children: childrenOf.get(category.id) ?? [],
  }))
}

export function indexById(categories: Category[]): Map<string, Category> {
  return new Map(categories.map((category) => [category.id, category]))
}

/** «Продукты · Пятёрочка» — подкатегория без родителя непонятна. */
export function fullName(category: Category, byId: Map<string, Category>): string {
  const parent = category.parent_id ? byId.get(category.parent_id) : undefined
  return parent ? `${parent.name} · ${category.name}` : category.name
}

/** Значок самой категории, а если его не задали — родительский. */
export function iconOf(category: Category, byId: Map<string, Category>): string {
  if (category.icon) return category.icon
  const parent = category.parent_id ? byId.get(category.parent_id) : undefined
  return parent?.icon || '•'
}
