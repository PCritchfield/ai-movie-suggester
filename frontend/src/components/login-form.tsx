"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiPost } from "@/lib/api/client";
import { ApiAuthError, ApiError } from "@/lib/api/types";
import type { LoginResponse } from "@/lib/api/types";

function mapError(err: unknown): string {
  if (err instanceof ApiAuthError) {
    if (err.status === 401) return "Invalid username or password.";
    return "Something went wrong. Please try again.";
  }
  if (err instanceof ApiError) {
    if (err.status === 502)
      return "Unable to reach the media server. Try again shortly.";
    if (err.status === 429) return "Too many login attempts. Please wait.";
    return "Something went wrong. Please try again.";
  }
  return "Could not connect to the server.";
}

interface LoginFormProps {
  reason?: string;
}

export function LoginForm({ reason }: LoginFormProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    const form = new FormData(e.currentTarget);
    const username = ((form.get("username") ?? "") as string).trim();
    const password = (form.get("password") ?? "") as string;

    if (!username || !password) {
      setError("Username and password are required.");
      return;
    }

    setIsPending(true);
    try {
      await apiPost<LoginResponse>("/api/auth/login", {
        username,
        password,
      });
      router.push("/");
    } catch (err) {
      setError(mapError(err));
    } finally {
      setIsPending(false);
    }
  }

  return (
    <Card className="w-full max-w-sm mx-auto">
      <CardHeader>
        <CardTitle className="text-center text-2xl">Sign in</CardTitle>
      </CardHeader>
      <CardContent>
        {reason === "session_expired" && (
          <p
            role="status"
            className="mb-4 rounded-md bg-muted p-3 text-sm text-muted-foreground"
          >
            Your session has expired. Please sign in again.
          </p>
        )}

        <form
          aria-label="Sign in"
          onSubmit={handleSubmit}
          className="space-y-4"
        >
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              autoFocus
              aria-invalid={!!error}
              aria-errormessage={error ? "form-error" : undefined}
              disabled={isPending}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              aria-invalid={!!error}
              aria-errormessage={error ? "form-error" : undefined}
              disabled={isPending}
            />
          </div>

          {error && (
            <p
              id="form-error"
              role="alert"
              className="text-sm text-destructive"
            >
              {error}
            </p>
          )}

          <Button
            type="submit"
            className="w-full min-h-11"
            disabled={isPending}
          >
            {isPending ? (
              <>
                <Loader2
                  className="mr-2 h-4 w-4 animate-spin"
                  aria-hidden="true"
                />
                Signing in...
              </>
            ) : (
              "Sign in"
            )}
          </Button>

          <span aria-live="polite" className="sr-only">
            {isPending ? "Signing in, please wait" : ""}
          </span>
        </form>
      </CardContent>
    </Card>
  );
}
