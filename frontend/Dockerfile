FROM node:22-alpine AS build
WORKDIR /app

COPY package.json yarn.lock* ./
RUN yarn install

COPY . .

ARG REACT_APP_BACKEND_URL
ARG PUBLIC_URL=/general
ENV REACT_APP_BACKEND_URL=${REACT_APP_BACKEND_URL}
ENV PUBLIC_URL=${PUBLIC_URL}

RUN yarn build

FROM nginx:alpine
ARG PUBLIC_URL=/general
COPY --from=build /app/build /usr/share/nginx/html${PUBLIC_URL}
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV PUBLIC_URL=${PUBLIC_URL}
ENV BACKEND_UPSTREAM=http://backend:8000

EXPOSE 80
