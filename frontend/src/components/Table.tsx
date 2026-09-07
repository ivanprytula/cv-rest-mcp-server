import type { ReactNode } from 'react'

// Shared cell classes for the three data tables (Revisions/Roadmap/Postings)
// — same border/padding/scroll-container pattern for all of them.
export function TableScroll({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto">{children}</div>
}

export function DataTable({ children }: { children: ReactNode }) {
  return <table className="min-w-120 w-full border-collapse">{children}</table>
}

export const th = 'border-b border-border px-3 py-2 text-left sm:px-3 max-sm:px-2 max-sm:text-sm'
