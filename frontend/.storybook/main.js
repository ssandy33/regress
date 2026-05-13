/** @type { import('@storybook/nextjs-vite').StorybookConfig } */
const config = {
  stories: [
    '../components/**/*.stories.@(js|jsx|mjs|ts|tsx)',
    '../components/**/*.mdx',
  ],
  addons: [
    '@storybook/addon-docs',
    '@storybook/addon-themes',
  ],
  framework: {
    name: '@storybook/nextjs-vite',
    options: {},
  },
};

export default config;
