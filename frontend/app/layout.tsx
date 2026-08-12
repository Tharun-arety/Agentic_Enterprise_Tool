import type { Metadata, Viewport } from "next";
import { Archivo, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { AgentChatProvider } from "@/components/AgentChatProvider";
import { AuthProvider } from "@/components/AuthProvider";

/*
 * Two families, one rule: Archivo carries the interface, IBM Plex Mono carries
 * every identifier and measurement. Plex was drawn for engineering
 * documentation and it shows — the identifiers read as a class of thing rather
 * than as more prose.
 */
const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Magnotherm — engineering operations",
    template: "%s · Magnotherm",
  },
  description:
    "Configuration, change, quality and supply evidence for refrigerant-free magnetocaloric cooling systems.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#eff0eb" },
    { media: "(prefers-color-scheme: dark)", color: "#0e1116" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${plexMono.variable} h-full antialiased`}
    >
      {/* The shell owns its own scrolling regions, so the body must not add
          another one on top. */}
      <body className="h-full overflow-hidden">
        <a
          href="#work-surface"
          className="bg-cold text-cold-ink sr-only rounded-chip px-3 py-2 text-sm font-semibold focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50"
        >
          Skip to content
        </a>
        <AuthProvider>
          <AgentChatProvider>{children}</AgentChatProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
