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
