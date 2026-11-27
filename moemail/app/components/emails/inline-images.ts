import type { AttachmentInfo } from "@/lib/attachments"

// 正文里 <img src="cid:…"> 引用的内嵌图片：由本页取回内容，换成 blob: 地址。
// 不能把下载地址写进邮件 HTML：分享页的下载地址里带着分享 token，邮件自己的 HTML 和 CSS
// 能读到 iframe 里的属性，还能把它拼进外链发出去。blob: 地址里没有任何凭据。
// 只处理整个 src 就是 cid: 的图片。返回清理函数，换邮件或卸载时调用。
export function loadInlineImages(
  doc: Document,
  attachments: AttachmentInfo[] | undefined,
  baseUrl: string | undefined
) {
  if (!baseUrl || !attachments?.length) return () => {}
  const byContentId = new Map<string, AttachmentInfo>()
  for (const a of attachments) {
    if (a.contentId && a.stored) byContentId.set(a.contentId.toLowerCase(), a)
  }
  if (byContentId.size === 0) return () => {}

  let cancelled = false
  const objectUrls: string[] = []

  doc.querySelectorAll<HTMLImageElement>("img[src]").forEach((img) => {
    const src = img.getAttribute("src")?.trim() ?? ""
    if (!/^cid:/i.test(src)) return
    let id = src.slice(4)
    try {
      id = decodeURIComponent(id)
    } catch {
      // 保留原样
    }
    const attachment = byContentId.get(id.trim().toLowerCase())
    if (!attachment) return

    fetch(`${baseUrl}/${attachment.index}`)
      .then((response) => (response.ok ? response.blob() : null))
      .then((blob) => {
        if (!blob || cancelled) return
        const url = URL.createObjectURL(blob)
        objectUrls.push(url)
        img.src = url
      })
      .catch(() => {})
  })

  return () => {
    cancelled = true
    objectUrls.forEach((url) => URL.revokeObjectURL(url))
  }
}
