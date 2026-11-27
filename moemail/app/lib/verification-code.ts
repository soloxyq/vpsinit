// 从邮件里找验证码，给阅读页的“一键复制”用。
// 只看“验证码”“code”这类关键词附近：后面 50 个字符内，或者前面 30 个字符内（“123456 is your code”）。
// 只认 4–8 位、至少带一个数字的大写字母数字组合，也认 “123 456” 这种中间带空格或横线的。
// 跳过年份，以及日期、时间、金额、电话号码里的数字。找不到就不显示：宁可漏掉，也不给出错的验证码。
// 不用正则的后行断言（Safari 16.4 以前不支持，整个脚本会解析失败）

const KEYWORD =
  /验证码|校验码|动态码|确认码|激活码|登录码|安全码|驗證碼|認證碼|確認碼|인증\s*(?:번호|코드)|認証コード|確認コード|verification code|security code|confirmation code|login code|sign[- ]?in code|one[- ]time (?:pass)?code|passcode|\botp\b|\bcode\b|\bpin\b/gi

// 第 1 组是前面的边界字符（或开头），第 2 组是候选的验证码
const CODE = /(^|[^A-Za-z0-9])(\d{3}[ -]\d{3}|[A-Z0-9]{4,8})(?![A-Za-z0-9])/g

// 只有 HTML 正文时取出其中的文字。用 DOMParser 而不是正则：邮件 HTML 由发件人决定，
// 用正则剥标签遇到大量不闭合的标签会非常慢；DOMParser 不运行脚本、不加载图片，耗时和长度成正比。
// 服务端渲染时没有 DOMParser，只看主题和纯文本正文（所以调用方要在页面挂载后再识别，前后结果才一致）
const htmlToText = (html: string) => {
  if (!html || typeof DOMParser === "undefined") return ""
  const doc = new DOMParser().parseFromString(html.slice(0, 200_000), "text/html")
  doc.querySelectorAll("style, script").forEach((el) => el.remove())
  // textContent 不会在块级元素之间加空格（“up:</p><p>739201</p><p>Code” 会粘成 “up:739201Code”），这里补上
  doc.querySelectorAll("p, div, br, tr, td, th, li, h1, h2, h3, h4, h5, h6").forEach((el) => el.append(" "))
  return doc.body?.textContent ?? ""
}

interface Candidate {
  code: string
  start: number
  end: number
}

// 整段文字里的候选验证码和它们的位置。在整段文字上找，不在切出来的窗口里找：窗口的切口会把验证码截断
function candidates(text: string): Candidate[] {
  const list: Candidate[] = []
  for (const m of text.matchAll(CODE)) {
    const start = (m.index ?? 0) + m[1].length
    const end = start + m[2].length
    const code = m[2].replace(/[ -]/g, "")
    if (!/\d/.test(code) || /^(19|20)\d\d$/.test(code)) continue
    // 紧挨着“分隔符加数字”的是日期、时间、金额、电话号码（2026-11-27、12.50、138-0013-8000）
    if (/^[-/.:,]\d/.test(text.slice(end, end + 2)) || /\d[-/.:,]$/.test(text.slice(Math.max(0, start - 2), start))) continue
    list.push({ code, start, end })
  }
  return list
}

export function findVerificationCode(subject: string, content?: string, html?: string): string | null {
  const body = content?.trim() ? content : htmlToText(html ?? "")
  // 去掉链接（网址里的数字不算）；空白压成一个空格（HTML 模板的缩进会把关键词和验证码隔得很远）
  const text = `${subject}\n${body}`.replace(/https?:\/\/\S+/g, " ").replace(/\s+/g, " ").slice(0, 5000)
  const codes = candidates(text)
  if (codes.length === 0) return null
  const keywords = Array.from(text.matchAll(KEYWORD), (m) => ({
    start: m.index ?? 0,
    end: (m.index ?? 0) + m[0].length,
  }))

  for (const k of keywords) {
    const after = codes.find((c) => c.start >= k.end && c.start < k.end + 50)
    if (after) return after.code
  }
  for (const k of keywords) {
    const before = codes.filter((c) => c.end <= k.start && c.start >= k.start - 30)
    if (before.length) return before[before.length - 1].code
  }
  return null
}
