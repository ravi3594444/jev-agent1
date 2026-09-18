import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Firehose",
  description: "Ask about everything Jev read today.",
};

// Set the theme before paint so a dark-mode reload never flashes white.
const THEME_BOOT = `(function(){try{var t=localStorage.getItem('fh-theme');if(t)document.documentElement.setAttribute('data-theme',t)}catch(e){}})()`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
