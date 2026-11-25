# Build from the repo root:  docker build -f ui/Dockerfile -t procurement-ui .
# The dataset/ folder (playbook + threads.csv) must be inside the build context.
FROM node:20-slim AS web
WORKDIR /w
COPY ui/web/package*.json ./
RUN npm ci
COPY ui/web .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY . .
COPY --from=web /dist ./ui/dist
ENV PORT=8080
EXPOSE 8080
CMD ["python", "ui/server.py", "--host", "0.0.0.0"]
