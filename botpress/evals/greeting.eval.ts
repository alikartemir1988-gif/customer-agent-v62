import { Eval } from '@botpress/evals'

export default new Eval({
  name: 'arabic-greeting',
  description: 'The Botpress layer preserves the owned core greeting behavior',
  tags: ['core', 'arabic', 'regression'],
  type: 'regression',
  conversation: [
    {
      user: 'مرحبا',
      assert: {
        response: [
          { contains: 'أهلاً وسهلاً' },
          { contains: 'المنتجات والأسعار' },
          { not_contains: 'غير متاحة' },
        ],
      },
    },
  ],
})
