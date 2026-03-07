import './globals.css';
import Providers from './providers';

export const metadata = {
  title: 'Regression Tool',
  description: 'Financial regression analysis tool',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
