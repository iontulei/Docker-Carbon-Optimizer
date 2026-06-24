# Un-optimized: DCO001 (full node:24.14) + DCO002 (consecutive RUNs) + DCO003 (dev deps in runtime)

####################################################################################################
## Build Packages

FROM node:22.15 AS builder

# Remove again once corepack >= 0.31 made it into base image
# (see https://github.com/directus/directus/issues/24514)
RUN npm install --global corepack@latest

RUN apt-get update && apt-get install -y python3 python3-setuptools build-essential

WORKDIR /directus

COPY package.json .
RUN corepack enable && corepack prepare

# Deploy as 'node' user to match pnpm setups in production image
# (see https://github.com/directus/directus/issues/23822)
RUN chown node:node .
USER node

ENV NODE_OPTIONS=--max-old-space-size=8192

COPY pnpm-lock.yaml .
RUN pnpm fetch

COPY --chown=node:node . .
RUN set -ex && \
    pnpm install --recursive --offline --frozen-lockfile && \
    npm_config_workspace_concurrency=2 pnpm run build && \
    pnpm --filter directus deploy --legacy --prod dist && \
    cd dist && \
    node -e "const f='package.json',{name,version,type,exports,bin}=require('./' +f),{packageManager}=require('../'+f);fs.writeFileSync(f,JSON.stringify({name,version,type,exports,bin,packageManager},null,2));" && \
    mkdir -p database extensions uploads

####################################################################################################
## Create Production Image

FROM node:22.15 AS runtime

RUN apt-get update && apt-get install -y gcc build-essential
RUN npm install --global pm2@5 corepack@latest

USER node

WORKDIR /directus

ENV \
	DB_CLIENT="sqlite3" \
	DB_FILENAME="/directus/database/database.sqlite" \
	NODE_ENV="production" \
	NPM_CONFIG_UPDATE_NOTIFIER="false"

COPY --from=builder --chown=node:node /directus/ecosystem.config.cjs .
COPY --from=builder --chown=node:node /directus/dist .

EXPOSE 8055

CMD : \
	&& node cli.js bootstrap \
	&& pm2-runtime start ecosystem.config.cjs \
	;
