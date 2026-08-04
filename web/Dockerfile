# Multi-stage: build the static SPA with Node, serve it with nginx. The dev-mode Vite
# server never runs in this image — production-style Compose always serves the built
# `dist/` output.
FROM node:20-slim AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
