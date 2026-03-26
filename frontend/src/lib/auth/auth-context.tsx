"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

interface AuthState {
  userId: string;
  username: string;
  serverName: string;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  clearAuth: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  userId: string;
  username: string;
  serverName: string;
  children: ReactNode;
}

export function AuthProvider({
  userId,
  username,
  serverName,
  children,
}: AuthProviderProps) {
  const [state, setState] = useState<AuthState>({
    userId,
    username,
    serverName,
    isAuthenticated: true,
  });

  const clearAuth = useCallback(() => {
    setState({
      userId: "",
      username: "",
      serverName: "",
      isAuthenticated: false,
    });
  }, []);

  return <AuthContext value={{ ...state, clearAuth }}>{children}</AuthContext>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
