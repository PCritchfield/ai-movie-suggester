"use client";

import { useAuth } from "@/lib/auth/auth-context";
import { LogoutButton } from "@/components/logout-button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function AuthHome() {
  const { username, serverName } = useAuth();

  return (
    <Card className="w-full max-w-sm mx-auto">
      <CardHeader>
        <CardTitle className="text-center text-2xl">
          ai-movie-suggester
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-center">
        <p className="text-muted-foreground">
          Signed in as <span className="font-medium text-foreground">{username}</span>
        </p>
        <p className="text-sm text-muted-foreground">
          Connected to {serverName}
        </p>
        <LogoutButton />
      </CardContent>
    </Card>
  );
}
