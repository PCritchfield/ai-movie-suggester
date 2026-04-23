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

/** Raised when the chosen Jellyfin device is no longer reachable (HTTP 409). */
export class DeviceOfflineError extends ApiError {
  constructor(body: unknown) {
    super(409, body);
    this.name = "DeviceOfflineError";
  }
}

/**
 * Raised when the play dispatch failed for a reason other than auth or device
 * offline (HTTP 500, transport error, unexpected backend state).
 */
export class PlaybackFailedError extends ApiError {
  constructor(status: number, body: unknown) {
    super(status, body);
    this.name = "PlaybackFailedError";
  }
}

// --- Device / Play types (Epic 4 Remote Control — mirroring backend models) ---

/** Mirrors backend DeviceType literal from backend/app/jellyfin/device_models.py */
export type DeviceType = "Tv" | "Mobile" | "Tablet" | "Other";

/** Mirrors backend Device Pydantic model from backend/app/jellyfin/device_models.py */
export interface Device {
  session_id: string;
  name: string;
  client: string;
  device_type: DeviceType;
}

/** Mirrors backend PlayRequest Pydantic model from backend/app/play/models.py */
export interface PlayRequest {
  item_id: string;
  session_id: string;
}

/** Mirrors backend PlayResponse Pydantic model from backend/app/play/models.py */
export interface PlayResponse {
  status: string;
  device_name: string;
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
  community_rating: number | null;
  runtime_minutes: number | null;
  jellyfin_web_url: string | null;
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
