import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/AuthProvider";

export const metadata: Metadata = {
  title: "Magnotherm Toolchain — PDM · QMS · Knowledge",
  description:
    "Agentic ERP for refrigerant-free magnetocaloric cooling systems: bill of materials, lab test metrics, and engineering knowledge search.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className="h-full antialiased"
    >
      {/* The shell owns its own scrolling regions, so the body must not add
          another one on top. */}
      <body className="h-full overflow-hidden"><AuthProvider>{children}</AuthProvider></body>
    </html>
  );
}
