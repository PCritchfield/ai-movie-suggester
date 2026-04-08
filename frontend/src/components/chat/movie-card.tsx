"use client";

import React, { useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { PosterPlaceholder } from "./poster-placeholder";
import type { SearchResultItem } from "@/lib/api/types";

interface MovieCardProps {
  item: SearchResultItem;
  onClick: () => void;
}

export function MovieCard({ item, onClick }: MovieCardProps) {
  const [posterError, setPosterError] = useState(false);

  const altText = item.year ? `${item.title} (${item.year})` : item.title;

  return (
    <Card
      size="sm"
      className="cursor-pointer transition-shadow hover:ring-2 hover:ring-primary/50"
    >
      <button
        type="button"
        onClick={onClick}
        className="w-full text-left min-h-[44px]"
        aria-label={`View details for ${item.title}`}
      >
        <div className="aspect-[2/3] overflow-hidden rounded-t-xl">
          {posterError || !item.poster_url ? (
            <PosterPlaceholder title={item.title} />
          ) : (
            <img
              src={item.poster_url}
              alt={altText}
              loading="lazy"
              className="h-full w-full object-cover"
              onError={() => setPosterError(true)}
            />
          )}
        </div>
        <CardHeader>
          <CardTitle>
            {item.title}
            {item.year && (
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                ({item.year})
              </span>
            )}
          </CardTitle>
        </CardHeader>
        {item.overview && (
          <CardContent>
            <p className="text-xs text-muted-foreground line-clamp-3">
              {item.overview}
            </p>
          </CardContent>
        )}
        {item.genres.length > 0 && (
          <CardContent>
            <div className="flex flex-wrap gap-1">
              {item.genres.slice(0, 3).map((genre) => (
                <span
                  key={genre}
                  className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
                >
                  {genre}
                </span>
              ))}
            </div>
          </CardContent>
        )}
      </button>
    </Card>
  );
}
