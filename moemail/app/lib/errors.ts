// message 是写给用户看的、可以原样返回给客户端的错误。
// 其它错误（数据库、网络、解析）的 message 可能带着内部细节：接口只回一句固定的文字，原文记到日志里
export class PublicError extends Error {}
