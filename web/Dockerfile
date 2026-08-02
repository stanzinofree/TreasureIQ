# TreasureIQ web client
#
# Multi-stage: the final image carries the Next.js standalone output and its
# runtime only — no source, no node_modules, no build toolchain.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Baked in at build time: NEXT_PUBLIC_* variables are inlined into the client
# bundle, so this is the URL the *browser* will call — it must be reachable from
# the host, not from inside the compose network.
ARG NEXT_PUBLIC_TREASUREIQ_API=http://localhost:8010
ENV NEXT_PUBLIC_TREASUREIQ_API=${NEXT_PUBLIC_TREASUREIQ_API}
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 10001 -S nodejs && adduser -u 10001 -S nextjs -G nodejs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
