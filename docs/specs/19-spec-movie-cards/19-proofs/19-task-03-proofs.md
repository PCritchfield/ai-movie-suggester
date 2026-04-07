# Task 3.0 — Movie Card Component + Responsive Layout — Proof Artifacts

## Test Results

```
Test Files   2 passed (2)
Tests        14 passed (14)
Duration     1.19s
```

### movie-card.test.tsx (9 tests)

- Renders title, year, overview, genres
- Overview truncated with line-clamp-3
- Only first 3 genres shown when > 3
- Poster img has correct alt text `"{title} ({year})"`
- Poster img has loading="lazy"
- Calls onClick when card clicked
- Calls onClick on Enter keypress
- Shows PosterPlaceholder on img error
- Passes axe accessibility audit

### card-carousel.test.tsx (5 tests)

- Renders correct number of MovieCard children
- Renders scroll indicator dots matching item count
- Carousel container has scroll-snap CSS classes
- Renders nothing when items is empty
- No dots for single item

## Components Created

- `poster-placeholder.tsx` — Film icon + title on muted background
- `movie-card.tsx` — Card with poster, title/year, overview (line-clamp-3), up to 3 genre pills
- `card-carousel.tsx` — Mobile: horizontal scroll with snap + dots; Desktop: 2-column grid
- `message-list.tsx` — CardCarousel integrated after assistant markdown block
