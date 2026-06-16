"use client";

import React, { useMemo } from "react";
import { CardCarousel } from "./card-carousel";
import type { PickItem, SearchResultItem } from "@/lib/api/types";

interface RecommendationSectionsProps {
  recommendations: SearchResultItem[];
  picks: PickItem[];
  onCardClick: (item: SearchResultItem) => void;
}

/**
 * Spec 27 — two-section card layout (Adorabelle ruling).
 *
 * The validated picks render first as a labelled "Recommended" carousel (in the
 * LLM's order, badged); the remaining candidates sit behind a collapsed
 * "More matches" disclosure. Two DISTINCT carousels — not an in-place mutation
 * of one scroll container — so a phone user mid-swipe is never stranded.
 *
 * `aria-live="polite"` is scoped to the section LABEL only (a single
 * announcement), never the cards, so screen readers aren't flooded per card.
 */
export function RecommendationSections({
  recommendations,
  picks,
  onCardClick,
}: RecommendationSectionsProps) {
  const byId = useMemo(
    () => new Map(recommendations.map((r) => [r.jellyfin_id, r])),
    [recommendations]
  );
  const pickIds = useMemo(
    () => new Set(picks.map((p) => p.jellyfin_id)),
    [picks]
  );

  // Recommended: picks in LLM order, resolved against the candidate set.
  const recommended = picks
    .map((p) => byId.get(p.jellyfin_id))
    .filter((r): r is SearchResultItem => r !== undefined);

  // More matches: candidates the model didn't pick.
  const rest = recommendations.filter((r) => !pickIds.has(r.jellyfin_id));

  if (recommended.length === 0) {
    // Defensive: no resolvable picks — fall back to a single plain carousel.
    return <CardCarousel items={recommendations} onCardClick={onCardClick} />;
  }

  return (
    <div className="mt-1">
      <p
        aria-live="polite"
        className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
      >
        Recommended
      </p>
      <CardCarousel items={recommended} onCardClick={onCardClick} isPick />

      {rest.length > 0 && (
        <details className="mt-3 group">
          <summary className="inline-flex min-h-11 cursor-pointer items-center text-sm font-medium text-muted-foreground hover:text-foreground">
            More matches ({rest.length})
          </summary>
          <CardCarousel items={rest} onCardClick={onCardClick} />
        </details>
      )}
    </div>
  );
}
