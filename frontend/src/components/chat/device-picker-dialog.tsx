"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  Tv,
  Smartphone,
  Tablet,
  MonitorSmartphone,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { fetchDevices, postPlay } from "@/lib/api/devices";
import { ApiAuthError, DeviceOfflineError } from "@/lib/api/types";
import type { Device, DeviceType, SearchResultItem } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";

interface DevicePickerDialogProps {
  item: SearchResultItem;
  open: boolean;
  onClose: () => void;
  onDispatched: (deviceName: string) => void | Promise<void>;
  /**
   * Test-only: forces the offline-banner rendering path without requiring a
   * real 409 dispatch. T4 will add an internal state path for production use.
   */
  forceOffline?: boolean;
}

const deviceTypeToIcon: Record<
  DeviceType,
  React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>
> = {
  Tv,
  Mobile: Smartphone,
  Tablet,
  Other: MonitorSmartphone,
};

export function DevicePickerDialog({
  item,
  open,
  onClose,
  onDispatched,
  forceOffline,
}: DevicePickerDialogProps) {
  const titleId = useId();
  const descId = useId();

  const { clearAuth } = useAuth();

  const [loading, setLoading] = useState(false);
  const [devices, setDevices] = useState<Device[]>([]);
  const [fetchError, setFetchError] = useState(false);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    null
  );
  const [showOfflineBanner, setShowOfflineBanner] = useState(false);

  // Ref guards — see spec Technical Considerations.
  const mountedRef = useRef(true);
  const dispatchInFlightRef = useRef(false);
  const fetchIdRef = useRef(0);
  // Tracks the previous open value so we can detect open false→true
  // transitions during render and reset visible state synchronously — this
  // prevents a one-frame flash of stale devices/error on reopen before the
  // open-effect runs runFetch (Copilot review on PR #208).
  const previousOpenRef = useRef<boolean | null>(null);

  if (previousOpenRef.current !== open) {
    previousOpenRef.current = open;
    if (open) {
      // Clean slate on every open transition: ensure the first post-open
      // paint shows the Loading skeleton, not stale devices/errors/offline
      // banner from the previous session.
      setLoading(true);
      setDevices([]);
      setFetchError(false);
      setShowOfflineBanner(false);
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const runFetch = useCallback(async () => {
    const myFetchId = ++fetchIdRef.current;
    setLoading(true);
    setFetchError(false);
    try {
      const data = await fetchDevices();
      if (!mountedRef.current) return;
      if (myFetchId !== fetchIdRef.current) return;
      setDevices(data);
    } catch (err) {
      if (!mountedRef.current) return;
      if (myFetchId !== fetchIdRef.current) return;
      // T2: all fetch errors (including ApiAuthError) surface as the generic
      // fetch-error state so the user can Refresh after re-authenticating.
      // T4 will split ApiAuthError into the clearAuth + toast flow used by
      // the dispatch handler (see PR #209).
      void err;
      setFetchError(true);
    } finally {
      if (!mountedRef.current) return;
      if (myFetchId === fetchIdRef.current) setLoading(false);
    }
  }, []);

  // Fresh fetch on every open false→true transition.
  //
  // Do NOT reset selectedSessionId or dispatchInFlightRef here — the
  // finally block of handleTap is the authoritative reset for both. Resetting
  // on reopen would create two bugs:
  //   - dispatchInFlightRef reset allows a second concurrent dispatch if the
  //     user closes + reopens mid-flight (Carrot review on PR #208).
  //   - selectedSessionId reset without also clearing the ref leaves rows
  //     visually enabled while handleTap silently no-ops (Copilot review).
  // If reopen happens mid-dispatch, the dispatching-row spinner stays visible
  // until postPlay resolves — correct reflection of actual state.
  useEffect(() => {
    if (open) {
      runFetch();
    }
  }, [open, runFetch]);

  const handleTap = useCallback(
    async (sessionId: string) => {
      if (dispatchInFlightRef.current) return;
      dispatchInFlightRef.current = true;
      setSelectedSessionId(sessionId);

      try {
        const result = await postPlay({
          item_id: item.jellyfin_id,
          session_id: sessionId,
        });
        if (!mountedRef.current) return;
        // Success — clear any prior offline state, notify parent, close picker
        setShowOfflineBanner(false);
        onDispatched(result.device_name);
        onClose();
      } catch (err) {
        if (!mountedRef.current) return;
        if (err instanceof ApiAuthError) {
          // Revoked session — match use-chat.ts:314 pattern: clear auth context
          // and surface a toast. Middleware handles redirect on next navigation.
          clearAuth();
          toast.error("Your session has expired. Please log in again.");
          onClose();
        } else if (err instanceof DeviceOfflineError) {
          // 409 — stay open, show banner, refetch device list in place.
          setShowOfflineBanner(true);
          runFetch();
        } else {
          // PlaybackFailedError, NetworkError, or anything else — generic
          // error toast with fixed copy (no err.message interpolation per
          // Angua's ruling on information-disclosure via toast strings).
          toast.error("Couldn't start playback. Please try again.");
          onClose();
        }
      } finally {
        if (mountedRef.current) setSelectedSessionId(null);
        dispatchInFlightRef.current = false;
      }
    },
    [clearAuth, item.jellyfin_id, onClose, onDispatched, runFetch]
  );

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent
        aria-labelledby={titleId}
        aria-describedby={descId}
        className="sm:max-w-md max-sm:fixed max-sm:bottom-0 max-sm:left-0 max-sm:right-0 max-sm:top-auto max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-t-2xl max-sm:rounded-b-none"
      >
        <DialogHeader>
          <DialogTitle id={titleId}>Cast to TV</DialogTitle>
          <DialogDescription id={descId}>
            Pick a device to play &ldquo;{item.title}&rdquo; on.
          </DialogDescription>
        </DialogHeader>

        {(forceOffline || showOfflineBanner) && (
          <div
            role="alert"
            aria-live="assertive"
            className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-foreground"
          >
            That device just went offline — pick another
          </div>
        )}

        {loading && (
          <div
            role="status"
            aria-label="Loading devices"
            className="flex min-h-[132px] items-center justify-center"
          >
            <Loader2
              className="h-6 w-6 animate-spin text-muted-foreground"
              aria-hidden={true}
            />
          </div>
        )}

        {!loading && fetchError && (
          <EmptyOrErrorState
            message="Couldn't load devices. Try again."
            onRefresh={runFetch}
          />
        )}

        {!loading && !fetchError && devices.length === 0 && (
          <EmptyOrErrorState
            message="No devices found. Open Jellyfin on your TV or phone, then refresh."
            onRefresh={runFetch}
          />
        )}

        {!loading && !fetchError && devices.length > 0 && (
          <ul className="flex flex-col gap-2">
            {devices.map((device) => {
              // Fallback to MonitorSmartphone if the backend sends a device_type
              // not in our union (e.g., newer backend, older frontend).
              const Icon =
                deviceTypeToIcon[device.device_type] ?? MonitorSmartphone;
              const isDispatching = selectedSessionId === device.session_id;
              const isDisabled = selectedSessionId != null && !isDispatching;
              return (
                <li key={device.session_id}>
                  <button
                    type="button"
                    disabled={isDisabled}
                    onClick={() => handleTap(device.session_id)}
                    aria-label={`Cast ${item.title} to ${device.name}, ${device.client}`}
                    className="flex w-full min-h-11 items-center gap-3 rounded-md border border-border bg-background px-3 py-2 text-left transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Icon
                      className="h-5 w-5 text-muted-foreground"
                      aria-hidden={true}
                    />
                    <span className="flex flex-1 flex-col">
                      <span className="text-sm font-medium text-foreground">
                        {device.name}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {device.client} · {device.device_type}
                      </span>
                    </span>
                    {isDispatching && (
                      <span
                        role="status"
                        aria-label={`Dispatching to ${device.name}`}
                      >
                        <Loader2
                          className="h-4 w-4 animate-spin text-muted-foreground"
                          aria-hidden={true}
                        />
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}

function EmptyOrErrorState({
  message,
  onRefresh,
}: {
  message: string;
  onRefresh: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-foreground">{message}</p>
      <button
        type="button"
        onClick={onRefresh}
        className="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        Refresh
      </button>
    </div>
  );
}
