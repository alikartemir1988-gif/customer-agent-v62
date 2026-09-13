import { Eval } from '@botpress/evals'

export default new Eval({
  name: 'product-price-and-delivery',
  description: 'Product facts and delivery answers still come from the owned core',
  tags: ['core', 'sales', 'regression'],
  type: 'regression',
  conversation: [
    {
      user: 'كم سعر الجهاز؟',
      assert: {
        response: [{ contains: '30$' }],
      },
    },
    {
      user: 'قديش التوصيل لدمشق؟',
      assert: {
        response: [
          { contains: 'التوصيل إلى دمشق' },
          { not_contains: 'غير متاحة' },
        ],
      },
    },
  ],
})
