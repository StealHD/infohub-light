import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

const staticTemplateUiImportRule = {
  meta: {
    type: 'problem',
    schema: [],
    messages: {
      restricted: '受控 UI 依赖和 CSS Modules 不得通过静态模板字符串动态导入。',
    },
  },
  create(context) {
    return {
      ImportExpression(node) {
        if (node.source.type !== 'TemplateLiteral' || node.source.expressions.length > 0) return
        const specifier = node.source.quasis.map((quasi) => quasi.value.cooked ?? quasi.value.raw).join('')
        if (/^(?:@mui\/|@emotion\/|@heroui\/)/.test(specifier) || /\.module\.css$/.test(specifier)) {
          context.report({ node, messageId: 'restricted' })
        }
      },
    }
  },
}

export default [
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**'] },
  {
    files: ['scripts/**/*.mjs'],
    languageOptions: { globals: { console: 'readonly', process: 'readonly', URL: 'readonly' } },
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: {
      inteliscope: { rules: { 'no-static-template-ui-import': staticTemplateUiImportRule } },
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      'no-undef': 'off',
      ...reactHooks.configs.flat.recommended.rules,
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
      '@typescript-eslint/no-explicit-any': 'error',
    },
  },
  {
    files: ['src/app/**/*.{ts,tsx}', 'src/features/**/*.{ts,tsx}'],
    ignores: ['src/**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [
          { group: ['@mui/*', '@emotion/*'], message: 'MUI 与 Emotion 已从生产前端移除。' },
          { group: ['@heroui/*'], message: 'HeroUI 必须通过 src/design-system 引入。' },
        ],
      }],
      'inteliscope/no-static-template-ui-import': 'error',
    },
  },
  {
    files: ['src/features/workbench-heroui/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': 'off',
      'inteliscope/no-static-template-ui-import': 'off',
    },
  },
]
