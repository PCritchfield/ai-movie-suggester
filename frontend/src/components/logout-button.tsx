"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiPost } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";

export function LogoutButton() {
  const router = useRouter();
  const { clearAuth } = useAuth();
  const [isPending, setIsPending] = useState(false);

  async function handleLogout() {
    setIsPending(true);
    try {
      await apiPost("/api/auth/logout");
      router.push("/login");
    } catch {
      clearAuth();
      router.push("/login?reason=session_expired");
    }
  }

  return (
    <>
      <Button
        variant="outline"
        className="min-h-11"
        disabled={isPending}
        onClick={handleLogout}
      >
        {isPending ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Signing out...
          </>
        ) : (
          "Sign out"
        )}
      </Button>
      <span aria-live="polite" className="sr-only">
        {isPending ? "Signing out, please wait" : ""}
      </span>
    </>
  );
}
