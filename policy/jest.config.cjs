const path = require('node:path');
const root = process.cwd();

module.exports = {
  rootDir: root,
  testEnvironment: 'node',
  roots: ['<rootDir>/src'],
  testMatch: ['**/__tests__/**/*.ts', '**/?(*.)+(spec|test).ts'],
  transform: {
    '^.+\\.tsx?$': [
      require.resolve('ts-jest', { paths: [root] }),
      { tsconfig: path.join(root, 'tsconfig.json') }
    ]
  },
  collectCoverageFrom: [
    'src/**/*.ts', '!src/**/*.d.ts', '!src/**/*.test.ts', '!src/**/__tests__/**'
  ],
  coverageDirectory: path.join(root, 'coverage'),
  coverageReporters: ['json', 'json-summary', 'lcov'],
  coverageThreshold: {
    global: { branches: 70, functions: 70, lines: 70, statements: 70 }
  },
  reporters: ['default', require.resolve('jest-junit', { paths: [root] })]
};
