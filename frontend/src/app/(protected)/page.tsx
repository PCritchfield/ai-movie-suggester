import { AuthHome } from "@/components/auth-home";

export default function ProtectedPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <AuthHome />
    </main>
  );
}
