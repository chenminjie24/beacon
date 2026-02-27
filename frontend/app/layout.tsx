import './globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'QMT 实盘中台',
  description: '聚宽/多平台信号接入 + QMT 执行中台'
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  )
}
