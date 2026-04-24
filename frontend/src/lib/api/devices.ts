import { apiGet, apiPost } from "./client";
import {
  ApiAuthError,
  ApiError,
  DeviceOfflineError,
  PlaybackFailedError,
} from "./types";
import type { Device, PlayRequest, PlayResponse } from "./types";

export async function fetchDevices(): Promise<Device[]> {
  return apiGet<Device[]>("/api/devices");
}

/**
 * Dispatch a play command to a Jellyfin session.
 *
 * Error mapping (per backend/app/play/router.py contract + parseResponse):
 *   200              → PlayResponse
 *   401 / 403        → ApiAuthError (passed through; picker's handleTap
 *                      calls clearAuth + toast.error on this class)
 *   409              → DeviceOfflineError (picker stays open, in-place refetch)
 *   Other HTTP 4xx/5xx → PlaybackFailedError (picker closes + toast.error)
 *   Non-HTTP (e.g. NetworkError from networkFetch) → re-thrown unwrapped,
 *                      handled by the picker's generic `else` branch as a
 *                      playback failure. Deliberately not wrapped — the
 *                      picker's catch treats any non-typed throw the same.
 *
 * Goes through `apiPost` (not raw `fetch`) so the CSRF header + session
 * cookie are always attached. Do not bypass this — the backend enforces
 * CSRF on `/api/play` and a raw-fetch bypass would silently drop it.
 */
export async function postPlay(req: PlayRequest): Promise<PlayResponse> {
  try {
    return await apiPost<PlayResponse>("/api/play", req);
  } catch (err) {
    // Catch ordering matters: ApiAuthError extends ApiError, so the
    // ApiAuthError guard MUST run before the ApiError branch — otherwise
    // auth errors would be swallowed into PlaybackFailedError and the picker
    // would never trigger the re-login flow. Any future ApiError subclass
    // with special handling belongs above this block.
    if (err instanceof ApiAuthError) {
      // Preserve auth errors as-is — the picker distinguishes ApiAuthError
      // in its handleTap catch to trigger clearAuth + the re-login toast.
      throw err;
    }
    if (err instanceof ApiError) {
      if (err.status === 409) {
        throw new DeviceOfflineError(err.body);
      }
      throw new PlaybackFailedError(err.status, err.body);
    }
    // NetworkError or anything non-ApiError — re-thrown unwrapped. The
    // picker's handleTap `else` branch treats any non-typed error as a
    // generic playback failure (shows the "Couldn't start playback" toast),
    // so wrapping in PlaybackFailedError here would be redundant.
    throw err;
  }
}
