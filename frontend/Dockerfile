# =============================================================================
# Stage 1: base — Node LTS + deterministic install
# =============================================================================
FROM node:22.22.2-alpine AS base

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# =============================================================================
# Stage 2: dev — full deps, runs next dev
# =============================================================================
FROM base AS dev
# Dev runs as root for bind-mount compatibility (see #43)

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]

# =============================================================================
# Stage 3: build — runs next build (standalone output)
# =============================================================================
FROM base AS build

ARG BACKEND_URL=http://localhost:8000
ENV BACKEND_URL=${BACKEND_URL}

COPY . .
ENV NODE_ENV=production
RUN npm run build

# =============================================================================
# Stage 4: prod — minimal image with standalone output, non-root user
# =============================================================================
FROM node:22.22.2-alpine AS prod

WORKDIR /app

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
