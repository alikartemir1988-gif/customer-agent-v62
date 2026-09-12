import {
  Conversation,
  configuration,
  secrets,
} from '@botpress/runtime'

type TextMessage = {
  messageId: string
  text: string
}

type CoreReply = {
  ok: true
  reply: string
}

class CoreRequestError extends Error {
  constructor(
    message: string,
    readonly retryable: boolean,
  ) {
    super(message)
  }
}

const TEMPORARY_FAILURE_REPLY =
  'عذراً، خدمة الطلبات غير متاحة للحظات. جرّب إرسال رسالتك مرة ثانية بعد قليل.'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const readTextMessage = (message: unknown): TextMessage | null => {
  if (!isRecord(message) || message.type !== 'text') {
    return null
  }

  if (typeof message.id !== 'string' || !isRecord(message.payload)) {
    return null
  }

  const text = message.payload.text

  if (typeof text !== 'string' || !text.trim()) {
    return null
  }

  return {
    messageId: message.id,
    text: text.trim(),
  }
}

const isCoreReply = (value: unknown): value is CoreReply =>
  isRecord(value) && value.ok === true && typeof value.reply === 'string'

const wait = async (milliseconds: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, milliseconds))

const coreEndpoint = (): { endpoint: string; secret: string } => {
  const coreApiUrl = configuration.coreApiUrl
  const secret = secrets.CORE_API_SECRET

  if (!coreApiUrl || !secret) {
    throw new CoreRequestError('Customer Agent core is not configured', false)
  }

  const baseUrl = new URL(coreApiUrl)
  const isLocalDevelopment =
    baseUrl.hostname === 'localhost' ||
    baseUrl.hostname === '127.0.0.1' ||
    baseUrl.hostname === '[::1]'

  if (baseUrl.protocol !== 'https:' && !isLocalDevelopment) {
    throw new CoreRequestError(
      'Customer Agent core URL must use HTTPS outside local development',
      false,
    )
  }

  return {
    endpoint: new URL('/integrations/botpress/message', baseUrl).toString(),
    secret,
  }
}

const requestCoreReply = async (
  conversationId: string,
  message: TextMessage,
): Promise<string> => {
  const { endpoint, secret } = coreEndpoint()
  let lastError: unknown

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Botpress-Secret': secret,
        },
        body: JSON.stringify({
          conversation_id: conversationId,
          message_id: message.messageId,
          text: message.text,
        }),
        signal: AbortSignal.timeout(15_000),
      })

      if (!response.ok) {
        throw new CoreRequestError(
          `Customer Agent core returned ${response.status}`,
          response.status === 409 || response.status >= 500,
        )
      }

      const payload: unknown = await response.json()

      if (!isCoreReply(payload)) {
        throw new CoreRequestError(
          'Customer Agent core returned an invalid response',
          false,
        )
      }

      return payload.reply
    } catch (error) {
      lastError = error
      const retryable =
        !(error instanceof CoreRequestError) || error.retryable

      if (!retryable || attempt === 2) {
        break
      }

      await wait(250)
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error('Customer Agent core request failed')
}

export default new Conversation({
  channel: '*',
  shouldInterrupt: () => false,
  handler: async ({ type, conversation, message }) => {
    if (type !== 'message') {
      return
    }

    const textMessage = readTextMessage(message)

    if (!textMessage) {
      await conversation.send({
        type: 'text',
        payload: {
          text: 'حالياً أستطيع معالجة الرسائل النصية فقط.',
        },
      })
      return
    }

    try {
      const reply = await requestCoreReply(conversation.id, textMessage)

      await conversation.send({
        type: 'text',
        payload: { text: reply },
      })
    } catch (error) {
      console.error(
        'Customer Agent core request failed',
        error instanceof Error ? error.message : 'unknown error',
      )

      await conversation.send({
        type: 'text',
        payload: { text: TEMPORARY_FAILURE_REPLY },
      })
    }
  },
})
