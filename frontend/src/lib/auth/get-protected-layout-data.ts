import { serverGet } from "@/lib/api/server";
import type { LoginResponse } from "@/lib/api/types";
import { ApiAuthError } from "@/lib/api/types";

interface UserData {
  userId: string;
  username: string;
  serverName: string;
}

type LayoutDataSuccess = { type: "success"; user: UserData };
type LayoutDataRedirect = { type: "redirect"; url: string };
export type LayoutData = LayoutDataSuccess | LayoutDataRedirect;

export async function getProtectedLayoutData(): Promise<LayoutData> {
  try {
    const data = await serverGet<LoginResponse>("/api/auth/me");
    return {
      type: "success",
      user: {
        userId: data.user_id,
        username: data.username,
        serverName: data.server_name,
      },
    };
  } catch (err) {
    if (!(err instanceof ApiAuthError)) {
      console.error("Unexpected error in getProtectedLayoutData:", err);
    }
    return {
      type: "redirect",
      url: "/login?reason=session_expired",
    };
  }
}
