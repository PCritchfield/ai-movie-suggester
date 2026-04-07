export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  user_id: string;
  username: string;
  server_name: string;
}

export interface ErrorResponse {
  detail: string;
}

export class NetworkError extends Error {
  constructor() {
    super("Server unreachable — check your connection");
    this.name = "NetworkError";
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`API error: ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export class ApiAuthError extends ApiError {
  declare readonly status: 401 | 403;

  constructor(status: 401 | 403, body: unknown) {
    super(status, body);
    this.name = "ApiAuthError";
  }
}

// --- Chat / Search types (mirroring backend models) ---

/** Mirrors backend SearchResultItem from backend/app/search/models.py */
export interface SearchResultItem {
  jellyfin_id: string;
  title: string;
  overview: string | null;
  genres: string[];
  year: number | null;
  score: number;
  poster_url: string;
}

/** Mirrors backend SearchStatus enum */
export type SearchStatus = "ok" | "no_embeddings" | "partial_embeddings";

/** Mirrors backend ChatErrorCode enum */
export type ChatErrorCode =
  | "generation_timeout"
  | "ollama_unavailable"
  | "search_unavailable"
  | "stream_interrupted"
  | "auth_expired"
  | "rate_limited";

// --- SSE Event types (discriminated union) ---

export interface MetadataEvent {
  type: "metadata";
  version: number;
  recommendations: SearchResultItem[];
  search_status: SearchStatus;
  turn_count: number;
}

export interface TextEvent {
  type: "text";
  content: string;
}

export interface DoneEvent {
  type: "done";
}

export interface ErrorEvent {
  type: "error";
  code: ChatErrorCode;
  message: string;
}

/** Discriminated union of all SSE event types from POST /api/chat */
export type SSEEvent = MetadataEvent | TextEvent | DoneEvent | ErrorEvent;

// --- Chat message for client state ---

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  recommendations?: SearchResultItem[];
  searchStatus?: SearchStatus;
  error?: { code: ChatErrorCode; message: string };
  isStreaming?: boolean;
}
