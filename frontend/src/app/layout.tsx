import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ai-movie-suggester",
  description: "AI-powered movie recommendations for Jellyfin",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
