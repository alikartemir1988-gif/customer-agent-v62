import { Eval } from '@botpress/evals'

export default new Eval({
  name: 'confirmed-order-flow',
  description: 'A full Arabic order remains review-first and confirmation-gated',
  tags: ['core', 'order', 'critical', 'regression'],
  type: 'regression',
  conversation: [
    {
      user: 'بدي جهازين',
      assert: {
        response: [{ contains: 'شو اسمك' }],
      },
    },
    {
      user: 'أحمد خالد',
      assert: {
        response: [{ contains: 'رقم الهاتف' }],
      },
    },
    {
      user: '0933123456',
      assert: {
        response: [{ contains: 'المدينة' }],
      },
    },
    {
      user: 'دمشق',
      assert: {
        response: [
          { contains: 'راجع طلبك' },
          { contains: 'الكمية: 2' },
          { contains: 'الإجمالي: 60$' },
        ],
      },
    },
    {
      user: 'بدي الأبيض',
      assert: {
        response: [
          { contains: 'راجع طلبك' },
          { contains: 'اللون: أبيض' },
        ],
      },
    },
    {
      user: 'تأكيد',
      assert: {
        response: [{ contains: 'تم تسجيل طلبك بنجاح' }],
      },
    },
    {
      user: 'تأكيد',
      assert: {
        response: [{ contains: 'مسجل مسبقاً' }],
      },
    },
  ],
})
