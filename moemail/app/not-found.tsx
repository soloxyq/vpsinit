import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "404 - 页面不存在",
  robots: {
    index: false,
    follow: false,
  },
}

// 根布局 app/layout.tsx 只透传 children（<html><body> 在 app/[locale]/layout.tsx 里），
// 未匹配任何语言路由的 404 请求会直接落到这里；如果不自带 <html><body>，
// 生成的 404.html 缺少文档根元素，浏览器水合失败会显示空白。
export default function NotFound() {
  return (
    <html lang="zh-CN">
      <head>
        <style>{`
          body {
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
            background: #ffffff;
            color: #111827;
          }
          .box { text-align: center; padding: 24px; }
          .code { font-size: 48px; font-weight: 700; margin: 0 0 8px; color: #826DD9; }
          .msg { font-size: 16px; margin: 0 0 24px; color: #4b5563; }
          .btn {
            display: inline-block;
            padding: 10px 20px;
            border-radius: 8px;
            background: #826DD9;
            color: #ffffff;
            text-decoration: none;
            font-size: 14px;
          }
          .btn:hover { opacity: 0.9; }
          @media (prefers-color-scheme: dark) {
            body { background: #111827; color: #f9fafb; }
            .msg { color: #9ca3af; }
          }
        `}</style>
      </head>
      <body>
        <main className="box">
          <h1 className="code">404</h1>
          <p className="msg">页面不存在 / Page not found</p>
          {/* 故意用完整跳转进入 [locale] 布局，不走客户端软导航 */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a className="btn" href="/">
            返回首页 / Back to Home
          </a>
        </main>
      </body>
    </html>
  )
}
