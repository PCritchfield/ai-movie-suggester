"use client";

import React, { useId, useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { PosterPlaceholder } from "./poster-placeholder";
import { DevicePickerDialog } from "./device-picker-dialog";
import type { SearchResultItem } from "@/lib/api/types";

interface CardDetailProps {
  item: SearchResultItem | null;
  open: boolean;
  onClose: () => void;
}

function formatRuntime(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${m}m`;
}

export function CardDetail({ item, open, onClose }: CardDetailProps) {
  const titleId = useId();
  const [posterError, setPosterError] = React.useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Reset poster error when item changes
  React.useEffect(() => {
    setPosterError(false);
  }, [item?.jellyfin_id]);

  if (!item) return null;

  return (
    <>
      <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
        <DialogContent
          aria-labelledby={titleId}
          className="max-h-[85vh] overflow-y-auto sm:max-w-md max-sm:fixed max-sm:bottom-0 max-sm:left-0 max-sm:right-0 max-sm:top-auto max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-t-2xl max-sm:rounded-b-none"
        >
          <div className="aspect-[2/3] w-full overflow-hidden rounded-lg">
            {posterError || !item.poster_url ? (
              <PosterPlaceholder title={item.title} />
            ) : (
              <img
                src={item.poster_url}
                alt={item.year ? `${item.title} (${item.year})` : item.title}
                className="h-full w-full object-cover"
                onError={() => setPosterError(true)}
              />
            )}
          </div>

          <DialogHeader>
            <DialogTitle id={titleId}>
              {item.title}
              {item.year && (
                <span className="ml-2 text-base font-normal text-muted-foreground">
                  ({item.year})
                </span>
              )}
            </DialogTitle>
            <DialogDescription className="sr-only">
              Movie details for {item.title}
            </DialogDescription>
          </DialogHeader>

          {/* Metadata row: rating + runtime */}
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            {item.community_rating != null && (
              <span>★ {item.community_rating.toFixed(1)}/10</span>
            )}
            {item.runtime_minutes != null && (
              <span>{formatRuntime(item.runtime_minutes)}</span>
            )}
          </div>

          {/* All genres */}
          {item.genres.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {item.genres.map((genre) => (
                <span
                  key={genre}
                  className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground"
                >
                  {genre}
                </span>
              ))}
            </div>
          )}

          {/* Full overview */}
          {item.overview && (
            <p className="text-sm leading-relaxed text-foreground">
              {item.overview}
            </p>
          )}

          {/* Action buttons: Cast to TV + View in Jellyfin */}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setPickerOpen(true)}
              className="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Cast to TV
            </button>
            {item.jellyfin_web_url && (
              <a
                href={item.jellyfin_web_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-11 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent"
              >
                View in Jellyfin
              </a>
            )}
          </div>
        </DialogContent>
      </Dialog>
      <DevicePickerDialog
        item={item}
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onDispatched={(deviceName) => {
          toast.success(`Now playing on ${deviceName}`);
        }}
      />
    </>
  );
}
