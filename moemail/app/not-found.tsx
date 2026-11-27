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
            font-family: Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
            background: #fafafb;
            color: #151923;
          }
          .box { text-align: center; padding: 24px; }
          .code { font-size: 48px; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 8px; color: #4f46e5; }
          .msg { font-size: 15px; margin: 0 0 24px; color: #6b7280; }
          .btn {
            display: inline-block;
            padding: 9px 20px;
            border-radius: 8px;
            background: #4f46e5;
            color: #ffffff;
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
          }
          .btn:hover { opacity: 0.92; }
          @media (prefers-color-scheme: dark) {
            body { background: #0b0d11; color: #f3f4f6; }
            .code { color: #6366f1; }
            .btn { background: #6366f1; }
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
