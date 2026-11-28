interface CursorData {
  timestamp: number
  id: string
}

export function encodeCursor(timestamp: number, id: string): string {
  const data: CursorData = { timestamp, id }
  return Buffer.from(JSON.stringify(data)).toString('base64')
}

export function decodeCursor(cursor: string): CursorData | null {
  try {
    const raw = JSON.parse(Buffer.from(cursor, 'base64').toString('utf8')) as Partial<CursorData> | null
    if (
      !raw ||
      typeof raw !== 'object' ||
      typeof raw.timestamp !== 'number' ||
      !Number.isFinite(raw.timestamp) ||
      typeof raw.id !== 'string' ||
      !raw.id
    ) {
      return null
    }
    return { timestamp: raw.timestamp, id: raw.id }
  } catch {
    return null
  }
}