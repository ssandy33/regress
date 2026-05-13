import { withThemeByClassName } from '@storybook/addon-themes';

// Load the project's real Tailwind v4 stylesheet so stories render with the
// exact same design tokens and `dark:` variants as the running app.
// See ../app/globals.css for the `@custom-variant dark` declaration that
// re-binds Tailwind v4's media-based dark variant to the `.dark` class.
import '../app/globals.css';

/** @type { import('@storybook/nextjs-vite').Preview } */
const preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    backgrounds: { disable: true },
  },
  decorators: [
    withThemeByClassName({
      themes: {
        light: '',
        dark: 'dark',
      },
      defaultTheme: 'light',
      // Apply the class to a wrapper element rather than <html>; matches the
      // way ThemeContext toggles `.dark` on the document root in-app.
      parentSelector: 'html',
    }),
  ],
};

export default preview;
