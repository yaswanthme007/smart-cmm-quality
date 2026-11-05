# Multi-stage: `dev` runs the Vite dev server (compose service `web`);
# `prod` serves the static build with Nginx (compose service `web-prod`).

FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM deps AS build
COPY . .
RUN npm run build

FROM nginx:1.29-alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
