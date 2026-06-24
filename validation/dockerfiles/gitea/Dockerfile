# Un-optimized: 5 rules
# DCO001 (full golang, has alpine variant) + DCO002 (consecutive RUNs)
# DCO004 (delete .dockerignore)
# DCO005 (single-stage compiled-language) + DCO006 (unpinned golang tag)
FROM golang

RUN apt-get update && \
    apt-get install -y git curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs

RUN npm install -g pnpm

WORKDIR /go/src/code.gitea.io/gitea

COPY . .

ENV TAGS="bindata timetzdata sqlite sqlite_unlock_notify"
ENV CGO_ENABLED=1
ENV GITEA_VERSION=dev

RUN pnpm install --frozen-lockfile
RUN make frontend
RUN make generate
RUN go build -tags "${TAGS}" -trimpath -o gitea .

EXPOSE 22 3000

CMD ["./gitea"]
