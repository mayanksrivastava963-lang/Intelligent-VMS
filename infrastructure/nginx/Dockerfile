FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:stable-alpine
ARG NGINX_CONFIG=local.conf
COPY infrastructure/nginx/${NGINX_CONFIG} /etc/nginx/conf.d/default.conf
COPY --from=frontend /build/dist /usr/share/nginx/html
EXPOSE 80
