'use client'

import type { ReactNode } from 'react'

type Props = {
  columns: string[]
  rows: Array<Array<string | number | ReactNode>>
}

export default function DataTable({ columns, rows }: Props) {
  return (
    <div className="card table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, idx) => (
            <tr key={idx}>
              {cells.map((cell, cidx) => (
                <td key={`${idx}-${cidx}`}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
