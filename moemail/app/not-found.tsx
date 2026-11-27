import type { Metadata } from "next"
import { inter } from "./fonts"

export const metadata: Metadata = {
  title: "404 - 页面不存在",
  robots: {
    index: false,
    follow: false,
  },
}

// 站内手动选的主题存在 localStorage（next-themes 的 storageKey），这个独立文档里没有 ThemeProvider，
// 所以在绘制前读一次，选了深色就给 <html> 加 dark 类。
const themeScript = `try{if(localStorage.getItem('temp-mail-theme')==='dark'){document.documentElement.classList.add('dark')}else if(localStorage.getItem('temp-mail-theme')==='light'){document.documentElement.classList.add('light')}}catch(e){}`

// 根布局 app/layout.tsx 只透传 children（<html><body> 在 app/[locale]/layout.tsx 里），
// 未匹配任何语言路由的 404 请求会直接落到这里；如果不自带 <html><body>，
// 生成的 404.html 缺少文档根元素，浏览器水合失败会显示空白。
export default function NotFound() {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <style>{`
          body {
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: var(--font-inter), -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
            background: #fafafb;
            color: #151923;
          }
          .box { text-align: center; padding: 24px; }
          .mark {
            width: 44px; height: 44px; margin: 0 auto 20px;
            display: grid; place-items: center;
            border-radius: 12px;
            background: rgba(79, 70, 229, 0.1);
            box-shadow: inset 0 0 0 1px rgba(79, 70, 229, 0.2);
            color: #4f46e5;
          }
          .code { font-size: 48px; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 8px; color: #151923; }
          .msg { font-size: 15px; margin: 0 0 24px; color: #636975; }
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
          .btn:focus-visible { outline: none; box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.35); }
          @media (prefers-color-scheme: dark) {
            html:not(.light) body { background: #0b0d11; color: #f3f4f6; }
            html:not(.light) .mark { background: rgba(129, 140, 248, 0.16); box-shadow: inset 0 0 0 1px rgba(129, 140, 248, 0.3); color: #8b92f5; }
            html:not(.light) .code { color: #f3f4f6; }
            html:not(.light) .btn { background: #8b92f5; color: #0f1115; }
            html:not(.light) .msg { color: #9ca3af; }
          }
          html.dark body { background: #0b0d11; color: #f3f4f6; }
          html.dark .mark { background: rgba(129, 140, 248, 0.16); box-shadow: inset 0 0 0 1px rgba(129, 140, 248, 0.3); color: #8b92f5; }
          html.dark .code { color: #f3f4f6; }
          html.dark .btn { background: #8b92f5; color: #0f1115; }
          html.dark .msg { color: #9ca3af; }
        `}</style>
      </head>
      <body className={inter.variable}>
        <main className="box">
          <div className="mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="2.5" y="4.5" width="19" height="15" rx="3" stroke="currentColor" strokeWidth="1.8" />
              <path
                d="M3.5 6.5L11.1 12.2C11.63 12.6 12.37 12.6 12.9 12.2L20.5 6.5"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
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
