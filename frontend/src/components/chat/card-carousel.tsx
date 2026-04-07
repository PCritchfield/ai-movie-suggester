"use client";

import React, { useRef, useState, useCallback, useEffect } from "react";
import { MovieCard } from "./movie-card";
import type { SearchResultItem } from "@/lib/api/types";

interface CardCarouselProps {
  items: SearchResultItem[];
  onCardClick: (item: SearchResultItem) => void;
}

export function CardCarousel({ items, onCardClick }: CardCarouselProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const scrollLeft = el.scrollLeft;
    const cardWidth = el.scrollWidth / items.length;
    const newIndex = Math.round(scrollLeft / cardWidth);
    setActiveIndex(Math.min(newIndex, items.length - 1));
  }, [items.length]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, [handleScroll]);

  if (items.length === 0) return null;

  return (
    <div className="mt-3">
      {/* Mobile: horizontal scroll carousel / Desktop: 2-column grid */}
      <div
        ref={scrollRef}
        className="flex gap-3 overflow-x-auto scroll-smooth snap-x snap-mandatory scroll-pl-3 md:grid md:grid-cols-2 md:gap-4 md:overflow-x-visible md:snap-none md:scroll-pl-0"
      >
        {items.map((item) => (
          <div
            key={item.jellyfin_id}
            className="w-[80vw] flex-shrink-0 snap-start md:w-auto"
          >
            <MovieCard item={item} onClick={() => onCardClick(item)} />
          </div>
        ))}
      </div>
      {/* Scroll indicator dots (mobile only) */}
      {items.length > 1 && (
        <div
          className="mt-2 flex justify-center gap-1.5 md:hidden"
          aria-hidden="true"
        >
          {items.map((item, index) => (
            <span
              key={item.jellyfin_id}
              className={`h-1.5 w-1.5 rounded-full transition-colors ${
                index === activeIndex
                  ? "bg-foreground"
                  : "bg-muted-foreground/30"
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
