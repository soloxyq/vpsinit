// 有效期选项。显示文字在各对话框的翻译里（emails.create / share / shareMessage 下的同名 key）
export type ExpiryKey = "oneHour" | "oneDay" | "threeDays" | "permanent"

export interface ExpiryOption {
  key: ExpiryKey
  value: number
}

export const EXPIRY_OPTIONS: ExpiryOption[] = [
  { key: "oneHour", value: 1000 * 60 * 60 },
  { key: "oneDay", value: 1000 * 60 * 60 * 24 },
  { key: "threeDays", value: 1000 * 60 * 60 * 24 * 3 },
  { key: "permanent", value: 0 }
]
