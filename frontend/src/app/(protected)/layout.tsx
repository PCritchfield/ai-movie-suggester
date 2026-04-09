import { redirect } from "next/navigation";
import { getProtectedLayoutData } from "@/lib/auth/get-protected-layout-data";
import { AuthProvider } from "@/lib/auth/auth-context";
import { InstallBanner } from "@/components/install-banner";

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const result = await getProtectedLayoutData();

  if (result.type === "redirect") {
    redirect(result.url);
  }

  return (
    <AuthProvider
      userId={result.user.userId}
      username={result.user.username}
      serverName={result.user.serverName}
    >
      {children}
      <InstallBanner />
    </AuthProvider>
  );
}
