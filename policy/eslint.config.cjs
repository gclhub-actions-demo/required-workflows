module.exports = {
  env: { es2021: true, node: true },
  extends: ['eslint:recommended', 'plugin:@typescript-eslint/recommended'],
  parser: require.resolve('@typescript-eslint/parser', { paths: [process.cwd()] }),
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  plugins: ['@typescript-eslint'],
  rules: {
    '@typescript-eslint/no-unused-vars': 'error',
    '@typescript-eslint/no-explicit-any': 'warn',
    'no-console': 'off'
  }
};
