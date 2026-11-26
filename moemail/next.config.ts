import withPWA from 'next-pwa'
import createNextIntlPlugin from 'next-intl/plugin'
import { setupDevPlatform } from '@cloudflare/next-on-pages/next-dev';

async function setup() {
  if (process.env.NODE_ENV === 'development') {
    await setupDevPlatform()
  }
}

setup()

const withNextIntl = createNextIntlPlugin('./app/i18n/request.ts')

const nextConfig = {
  // 不允许任何页面用 iframe 嵌入本站，防点击劫持（同主域名下其它子域名上的页面也不行）。
  // 邮件正文用的是本站自己的 about:blank iframe，不经过网络响应，不受这两个头影响。
  // 在 next-on-pages 上这里只作用于静态文件；页面和接口的响应由 middleware.ts 加同样的头。
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'Content-Security-Policy', value: "frame-ancestors 'none'" },
          { key: 'X-Frame-Options', value: 'DENY' },
        ],
      },
    ]
  },
  // 图片直接用原地址，不走 /_next/image。Cloudflare Pages 上这个接口本来就不做任何优化，只是原样转发；
  // 而 next-on-pages 的实现能被 url=/\host/… 这类写法骗去抓取任意外部地址，并把对方的 Set-Cookie 转发给访问者。
  // 根目录的 _routes.json 把 /_next/image* 排除在 worker 之外，这个接口在线上不可达，两处要一起保留。
  images: {
    unoptimized: true,
  },
};

const withPWAConfigured = withPWA({
  dest: 'public',
  register: true,
  skipWaiting: true,
  disable: process.env.NODE_ENV === 'development',
}) as any

const configWithPWA = withPWAConfigured(nextConfig as any) as any

export default withNextIntl(configWithPWA)
