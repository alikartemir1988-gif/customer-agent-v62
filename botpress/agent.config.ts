import { defineConfig, z } from '@botpress/runtime'

export default defineConfig({
  name: 'customer-agent-v63-lab',
  description:
    'Botpress evaluation and customer-service layer backed by the owned Customer Agent V6.3.2 core',

  bot: {
    state: z.object({}),
  },

  user: {
    state: z.object({}),
  },

  configuration: {
    schema: z.object({
      coreApiUrl: z
        .string()
        .url()
        .default('http://localhost:8000')
        .describe('Public HTTPS base URL of the owned Customer Agent core'),
    }),
  },

  secrets: {
    CORE_API_SECRET: {
      description:
        'Must equal BOTPRESS_INTEGRATION_SECRET on the Customer Agent core',
    },
  },
})
