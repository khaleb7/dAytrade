# syntax=docker/dockerfile:1
# Build from the repository root (the directory that contains apps/).
FROM node:22-bookworm-slim AS build
WORKDIR /src
COPY apps/daytrader/package.json apps/daytrader/package-lock.json ./
RUN npm ci
COPY apps/daytrader/tsconfig.json ./
COPY apps/daytrader/src ./src
RUN npm run build

FROM gcr.io/distroless/nodejs22-debian12
WORKDIR /app
COPY --from=build /src/dist ./dist
COPY --from=build /src/node_modules ./node_modules
COPY --from=build /src/package.json ./
COPY apps/daytrader/prompts ./prompts
ENV NODE_ENV=production \
    DAYTRADE_WORK=/work
USER nonroot
ENTRYPOINT ["/nodejs/bin/node", "dist/cli.js"]
