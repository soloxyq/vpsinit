"use client"

import { useEffect, useState } from "react"
import { useTranslations } from "next-intl"
import { EmailList } from "./email-list"
import { MessageListContainer } from "./message-list-container"
import { MessageView } from "./message-view"
import { SendDialog } from "./send-dialog"
import { EditNoteDialog } from "./edit-note-dialog"
import { cn } from "@/lib/utils"
import { useCopy } from "@/hooks/use-copy"
import { useSendPermission } from "@/hooks/use-send-permission"
import { useMediaQuery } from "@/hooks/use-media-query"
import { useUnreadCounts } from "@/hooks/use-unread-counts"
import { Copy, Inbox, MailOpen } from "lucide-react"
import { EmptyState } from "@/components/ui/empty-state"

interface Email {
  id: string
  address: string
  note?: string | null
}

export function ThreeColumnLayout() {
  const t = useTranslations("emails.layout")
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null)
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null)
  const [selectedMessageType, setSelectedMessageType] = useState<'received' | 'sent'>('received')
  const [refreshTrigger, setRefreshTrigger] = useState(0)
  const [noteUpdate, setNoteUpdate] = useState<{ id: string; note: string | null; seq: number } | null>(null)
  const { copyToClipboard } = useCopy()
  const { canSend: canSendEmails } = useSendPermission()
  // 桌面和手机两套布局平时只挂载当前屏幕用的那一套（断点和下面的 lg: 一致）。两套都挂着的话，
  // 被 CSS 藏起来的那套也在轮询邮件列表、也会再请求一遍邮件正文。
  // - 首次渲染还不知道屏幕宽度（null），两套都渲染，和服务端输出一致。
  // - 之后宽度跨过断点（旋转平板、把窗口贴到半屏）时，把另一套也挂上，原来那套不卸载：
  //   它里面开着的对话框、填了一半的内容都是组件自己的状态，卸载就丢了。
  //   代价是这以后两套并存、各管各的列表（在一套里删掉的邮件，另一套里要换个邮箱或刷新页面才消失），
  //   也就是改成只挂一套之前的老样子。刷新页面后又只挂一套。
  const isDesktop = useMediaQuery("(min-width: 1024px)")
  const [shown, setShown] = useState({ desktop: false, mobile: false })
  useEffect(() => {
    if (isDesktop === null) return
    const layout = isDesktop ? "desktop" : "mobile"
    setShown(prev => (prev[layout] ? prev : { ...prev, [layout]: true }))
  }, [isDesktop])
  const showDesktop = isDesktop !== false || shown.desktop
  const showMobile = isDesktop !== true || shown.mobile
  const { counts: unreadCounts, refresh: refreshUnread, decrementLocal: decrementUnread } = useUnreadCounts()

  const columnClass = "border border-border/80 bg-card rounded-xl shadow-sm overflow-hidden flex flex-col"
  const headerClass = "h-11 px-3.5 py-0 border-b border-border/70 bg-muted/30 flex items-center justify-between shrink-0"
  const titleClass = "text-[13px] font-semibold text-foreground w-full overflow-hidden"
  const copyButtonClass = "inline-flex items-center justify-center size-8 lg:size-6 shrink-0 rounded-md text-muted-foreground hover:text-primary hover:bg-accent active:bg-accent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
  const backButtonClass = "inline-flex items-center h-9 -ml-2 px-2 shrink-0 rounded-md text-sm text-primary hover:bg-primary/10 active:bg-primary/15 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"

  // 移动端视图逻辑
  const getMobileView = () => {
    if (selectedMessageId) return "message"
    if (selectedEmail) return "emails"
    return "list"
  }

  const mobileView = getMobileView()

  const copyEmailAddress = () => {
    copyToClipboard(selectedEmail?.address || "")
  }

  const handleMessageSelect = (messageId: string | null, messageType: 'received' | 'sent' = 'received') => {
    setSelectedMessageId(messageId)
    setSelectedMessageType(messageType)
  }

  const handleSendSuccess = () => {
    setRefreshTrigger(prev => prev + 1)
  }

  const handleNoteUpdated = (emailId: string, note: string | null) => {
    setSelectedEmail(prev => (prev && prev.id === emailId ? { ...prev, note } : prev))
    setNoteUpdate(prev => ({ id: emailId, note, seq: (prev?.seq ?? 0) + 1 }))
  }

  return (
    <div className="pb-5 pt-20 h-full flex flex-col">
      {/* 桌面端三栏布局 */}
      {showDesktop && (
      <div className="hidden lg:grid grid-cols-12 gap-4 h-full min-h-0">
        <div className={cn("col-span-3", columnClass)}>
          <div className={headerClass}>
            <h2 className={titleClass}>{t("myEmails")}</h2>
          </div>
          <div className="flex-1 overflow-auto">
            <EmailList
              onEmailSelect={(email) => {
                setSelectedEmail(email)
                setSelectedMessageId(null)
              }}
              selectedEmailId={selectedEmail?.id}
              unreadCounts={unreadCounts}
              updatedNote={noteUpdate}
              ready={isDesktop !== null}
            />
          </div>
        </div>

        <div className={cn("col-span-4", columnClass)}>
          <div className={headerClass}>
            <h2 className={titleClass}>
              {selectedEmail ? (
                <div className="w-full flex justify-between items-center gap-2">
                  <div className="flex items-center gap-1 min-w-0">
                    <span className="truncate min-w-0 font-mono text-[13px]">{selectedEmail.address}</span>
                    <button
                      type="button"
                      className={copyButtonClass}
                      onClick={copyEmailAddress}
                    >
                      <Copy className="size-3.5" />
                    </button>
                    <EditNoteDialog
                      emailId={selectedEmail.id}
                      emailAddress={selectedEmail.address}
                      initialNote={selectedEmail.note}
                      triggerClassName={copyButtonClass}
                      onNoteUpdated={handleNoteUpdated}
                    />
                  </div>
                  {selectedEmail && canSendEmails && (
                    <SendDialog 
                      emailId={selectedEmail.id} 
                      fromAddress={selectedEmail.address}
                      onSendSuccess={handleSendSuccess}
                    />
                  )}
                </div>
              ) : null}
            </h2>
          </div>
          {selectedEmail ? (
            <div className="flex-1 overflow-auto">
              <MessageListContainer
                email={selectedEmail}
                onMessageSelect={handleMessageSelect}
                selectedMessageId={selectedMessageId}
                refreshTrigger={refreshTrigger}
                unreadCount={unreadCounts[selectedEmail.id] ?? 0}
                onUnreadChange={refreshUnread}
                onUnreadDecrement={() => decrementUnread(selectedEmail.id)}
                canSend={canSendEmails}
              />
            </div>
          ) : (
            <div className="flex-1 min-h-0">
              <EmptyState icon={Inbox} title={t("selectEmail")} />
            </div>
          )}
        </div>

        <div className={cn("col-span-5", columnClass)}>
          <div className={headerClass}>
            <h2 className={titleClass}>
              {t("messageContent")}
            </h2>
          </div>
          {selectedEmail && selectedMessageId ? (
            <div className="flex-1 overflow-auto">
              <MessageView
                emailId={selectedEmail.id}
                messageId={selectedMessageId}
                messageType={selectedMessageType}
                onClose={() => setSelectedMessageId(null)}
                onRead={refreshUnread}
              />
            </div>
          ) : (
            <div className="flex-1 min-h-0">
              <EmptyState icon={MailOpen} title={t("selectMessage")} />
            </div>
          )}
        </div>
      </div>
      )}

      {/* 移动端单栏布局 */}
      {showMobile && (
      <div className="lg:hidden h-full min-h-0">
        <div className={cn("h-full", columnClass)}>
          {/* 用隐藏代替卸载：打开邮箱或邮件再返回时，保留左栏筛选词、中栏搜索结果与标签页状态 */}
          <div className={mobileView === "list" ? "h-full flex flex-col" : "hidden"}>
            <div className={headerClass}>
              <h2 className={titleClass}>{t("myEmails")}</h2>
            </div>
            <div className="flex-1 overflow-auto">
              <EmailList
                onEmailSelect={(email) => {
                  setSelectedEmail(email)
                  setSelectedMessageId(null)
                }}
                selectedEmailId={selectedEmail?.id}
                unreadCounts={unreadCounts}
                updatedNote={noteUpdate}
                ready={isDesktop !== null}
              />
            </div>
          </div>

          {selectedEmail && (
            <div className={mobileView === "emails" ? "h-full flex flex-col" : "hidden"}>
              <div className={cn(headerClass, "gap-2")}>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedEmail(null)
                    setSelectedMessageId(null)
                  }}
                  className={backButtonClass}
                >
                  {t("backToEmailList")}
                </button>
                <div className="flex-1 flex justify-between items-center gap-2 min-w-0">
                  <div className="flex items-center gap-1 min-w-0">
                    <span className="truncate min-w-0 flex-1 text-right font-mono text-[13px]">{selectedEmail.address}</span>
                    <button
                      type="button"
                      className={copyButtonClass}
                      onClick={copyEmailAddress}
                    >
                      <Copy className="size-3.5" />
                    </button>
                    <EditNoteDialog
                      emailId={selectedEmail.id}
                      emailAddress={selectedEmail.address}
                      initialNote={selectedEmail.note}
                      triggerClassName={copyButtonClass}
                      onNoteUpdated={handleNoteUpdated}
                    />
                  </div>
                  {canSendEmails && (
                    <SendDialog 
                      emailId={selectedEmail.id} 
                      fromAddress={selectedEmail.address}
                      onSendSuccess={handleSendSuccess}
                    />
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-auto">
                <MessageListContainer
                  email={selectedEmail}
                  onMessageSelect={handleMessageSelect}
                  selectedMessageId={selectedMessageId}
                  refreshTrigger={refreshTrigger}
                  unreadCount={unreadCounts[selectedEmail.id] ?? 0}
                  onUnreadChange={refreshUnread}
                  onUnreadDecrement={() => decrementUnread(selectedEmail.id)}
                  canSend={canSendEmails}
                />
              </div>
            </div>
          )}

          {mobileView === "message" && selectedEmail && selectedMessageId && (
            <div className="h-full flex flex-col">
              <div className={cn(headerClass, "gap-2")}>
                <button
                  type="button"
                  onClick={() => setSelectedMessageId(null)}
                  className={backButtonClass}
                >
                  {t("backToMessageList")}
                </button>
                <span className="text-sm font-medium truncate min-w-0">{t("messageContent")}</span>
              </div>
              <div className="flex-1 overflow-auto">
                <MessageView
                  emailId={selectedEmail.id}
                  messageId={selectedMessageId}
                  messageType={selectedMessageType}
                  onClose={() => setSelectedMessageId(null)}
                  onRead={refreshUnread}
                />
              </div>
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  )
}