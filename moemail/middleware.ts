import { resolveRequestAuth } from "@/lib/auth"
import { NextResponse } from "next/server"
import { i18n, type Locale } from "@/i18n/config"
import { hasPermission, PERMISSIONS, type Permission } from "@/lib/permissions"

// 每个 /api 前缀需要的权限，null 表示登录即可。
// 不在表里的 /api 路径一律拒绝：新增接口要先在这里登记。
const API_PERMISSIONS: [string, Permission | null][] = [
  ['/api/emails', PERMISSIONS.MANAGE_EMAIL],
  ['/api/webhook', PERMISSIONS.MANAGE_WEBHOOK],
  ['/api/roles/init-emperor', null],
  ['/api/account', null],
  ['/api/roles', PERMISSIONS.PROMOTE_USER],
  ['/api/users', PERMISSIONS.PROMOTE_USER],
  ['/api/config', PERMISSIONS.MANAGE_CONFIG],
  ['/api/api-keys', PERMISSIONS.MANAGE_API_KEY],
]

// 不需要登录的接口：登录、注册，以及凭链接访问的分享内容
const PUBLIC_API_ROUTES = ['/api/auth', '/api/shared']

const isUnder = (path: string, route: string) =>
  path === route || path.startsWith(route + '/')

// API Key 只能用于邮箱接口和只读站点配置（GET /api/config），不能改配置或读发件服务密钥
const isApiKeyAllowed = (apiPath: string, method: string) =>
  isUnder(apiPath, '/api/emails') || (apiPath === '/api/config' && method === 'GET')

// 会话靠 Cookie 认证，而浏览器会替任何页面带上 Cookie，所以写请求必须确认是本站页面发起的。
function isCrossSiteWrite(request: Request, url: URL) {
  if (['GET', 'HEAD', 'OPTIONS'].includes(request.method)) return false

  // Sec-Fetch-Site 由浏览器填写，页面脚本改不了
  const fetchSite = request.headers.get('Sec-Fetch-Site')
  if (fetchSite) return fetchSite !== 'same-origin' && fetchSite !== 'none'

  // 旧浏览器没有它，退而比较 Origin。两个头都没有的是非浏览器客户端，不会替别人带 Cookie
  const origin = request.headers.get('Origin')
  return !!origin && origin !== url.origin
}

// 不允许任何页面用 iframe 嵌入本站，防点击劫持。next.config.ts 的 headers() 也配了同样的头，
// 但在 next-on-pages 上那里只作用于静态文件，经过中间件的页面和接口拿不到，所以这里再加一遍。
const ANTI_FRAMING_HEADERS: [string, string][] = [
  ['Content-Security-Policy', "frame-ancestors 'none'"],
  ['X-Frame-Options', 'DENY'],
]

export async function middleware(request: Request) {
  const response = await handle(request)
  for (const [key, value] of ANTI_FRAMING_HEADERS) {
    response.headers.set(key, value)
  }
  return response
}

async function handle(request: Request): Promise<NextResponse> {
  const url = new URL(request.url)
  const pathname = url.pathname
  // 路由匹配不区分大小写（/api/EMAILS 也会进到 /api/emails 的处理函数），鉴权统一按小写判断
  const apiPath = pathname.toLowerCase()

  // 这里拿到的基本是原始路径（Next 只还原了两处：规范写法的 /_next/data/<buildId>/x.json 变回 /x，结尾小写的 .rsc 被去掉），
  // 路由器却按改写后的路径选处理函数。下面两类写法会落到 /api 的处理函数上，路径却不在 /api 下，
  // 后面按路径做的检查就对不上：
  //   /_next/data/<buildId>/api/…  路由器去掉前缀再匹配（不区分大小写，结尾也不必是 .json）
  //   //<任意>/api/…               改写时被当成“//主机/路径”重新解析，前面那段被丢掉
  // 本站只用 App Router，用不到这两类地址，一律 404。
  if (apiPath.startsWith('/_next/data/') || pathname.startsWith('//')) {
    return NextResponse.json(
      { error: "Not Found" },
      { status: 404 }
    )
  }

  if (isUnder(apiPath, '/api')) {
    if (PUBLIC_API_ROUTES.some(route => isUnder(apiPath, route))) {
      return NextResponse.next()
    }

    const hasApiKey = !!request.headers.get("X-API-Key")
    if (hasApiKey) {
      if (!isApiKeyAllowed(apiPath, request.method)) {
        return NextResponse.json(
          { error: "无权限查看" },
          { status: 403 }
        )
      }
    } else if (isCrossSiteWrite(request, url)) {
      return NextResponse.json(
        { error: "跨站请求被拒绝" },
        { status: 403 }
      )
    }

    const snap = await resolveRequestAuth(request.headers)
    if (!snap.userId) {
      return NextResponse.json(
        { error: hasApiKey ? "无效的 API Key" : "未授权" },
        { status: 401 }
      )
    }

    if (apiPath === '/api/config' && request.method === 'GET') {
      return NextResponse.next()
    }

    const rule = API_PERMISSIONS.find(([route]) => isUnder(apiPath, route))
    const hasAccess = !!rule && (rule[1] === null || hasPermission(snap.roles, rule[1]))

    if (!hasAccess) {
      return NextResponse.json(
        { error: "权限不足" },
        { status: 403 }
      )
    }

    return NextResponse.next()
  }

  // 页面只接受 GET/HEAD。本站没有 Server Actions，页面路径收到的写请求没有正当用途，
  // 而 App Router 处理这类请求的代码（反序列化请求体）是 Next 历次安全公告集中的地方，干脆不让它们进去。
  // 以后要加 Server Action，得先放开这里。
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return NextResponse.json(
      { error: "Method Not Allowed" },
      { status: 405, headers: { Allow: 'GET, HEAD' } }
    )
  }

  // 带点号的路径（静态文件、/en.rsc 这类 RSC 请求）和 /_next 下的路径不做语言跳转
  if (pathname.startsWith('/_next/') || /\.[^/]*$/.test(pathname)) {
    return NextResponse.next()
  }

  // Pages: 语言前缀
  const segments = pathname.split('/')
  const maybeLocale = segments[1]
  const hasLocalePrefix = i18n.locales.includes(maybeLocale as any)
  if (!hasLocalePrefix) {
    const cookieLocale = request.headers.get('Cookie')?.match(/NEXT_LOCALE=([^;]+)/)?.[1]
    const acceptLanguage = request.headers.get('Accept-Language')
    const preferredLocale = resolvePreferredLocale(cookieLocale, acceptLanguage)
    const targetLocale = preferredLocale ?? i18n.defaultLocale
    const redirectURL = new URL(`/${targetLocale}${pathname}${url.search}`, request.url)
    return NextResponse.redirect(redirectURL)
  }

  return NextResponse.next()
}

function resolvePreferredLocale(cookieLocale: string | undefined, acceptLanguageHeader: string | null): Locale | null {
  if (cookieLocale && i18n.locales.includes(cookieLocale as Locale)) {
    return cookieLocale as Locale
  }

  if (!acceptLanguageHeader) return null

  const candidates = parseAcceptLanguage(acceptLanguageHeader)
  for (const lang of candidates) {
    const match = matchLocale(lang)
    if (match) {
      return match
    }
  }

  return null
}

function parseAcceptLanguage(header: string): string[] {
  return header
    .split(',')
    .map((part) => {
      const [lang, ...params] = part.trim().split(';')
      const qualityParam = params.find((param) => param.trim().startsWith('q='))
      const quality = qualityParam ? parseFloat(qualityParam.split('=')[1]) : 1
      return { lang: lang.toLowerCase(), quality: isNaN(quality) ? 1 : quality }
    })
    .sort((a, b) => b.quality - a.quality)
    .map((entry) => entry.lang)
}

function matchLocale(lang: string): Locale | null {
  const exactMatch = i18n.locales.find((locale) => locale.toLowerCase() === lang)
  if (exactMatch) return exactMatch

  const base = lang.split('-')[0]

  // Handle Chinese variants with explicit regions or scripts
  if (base === 'zh') {
    if (lang.includes('tw') || lang.includes('hk') || lang.includes('mo') || lang.includes('hant')) {
      return 'zh-TW'
    }
    if (lang.includes('cn') || lang.includes('sg') || lang.includes('hans')) {
      return 'zh-CN'
    }
    // default Chinese fallback
    return 'zh-CN'
  }

  const baseMatch = i18n.locales.find((locale) => locale.toLowerCase().split('-')[0] === base)
  if (baseMatch) return baseMatch

  return null
}

export const config = {
  matcher: [
    // 除构建产物外的所有路径，包括带点号的（/en.rsc 这类写法同样会进到页面的处理函数，
    // 页面的方法限制和防嵌套头都要覆盖到）
    '/((?!_next/static/).*)',
    '/api/:path*',
  ]
} 
