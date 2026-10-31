FROM node:22-alpine AS frontend_build

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./

RUN npm ci

COPY frontend/ ./

RUN npm run build


FROM nginx:stable-alpine

COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template

COPY --from=frontend_build /build/dist/ /usr/share/nginx/html/