# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
FROM node@sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d AS frontend-builder
WORKDIR /label-studio/web
ENV BUILD_NO_SERVER=true BUILD_NO_HASH=true BUILD_NO_CHUNKS=true BUILD_MODULE=true \
    NODE_ENV=production NODE_OPTIONS="--max-old-space-size=4096" NX_DAEMON=false
COPY web/package.json web/yarn.lock ./
# Platform binaries are locked npm packages. No floating OS build dependencies
# or dependency lifecycle scripts are needed for this browser-only build.
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn,id=oidc-yarn \
    yarn install --frozen-lockfile --ignore-engines --ignore-scripts --non-interactive --production=false
COPY web ./
COPY pyproject.toml ../pyproject.toml
RUN yarn build

# Release 1.23.2; rebuild the stock frontend with focused authentication hooks.
FROM heartexlabs/label-studio@sha256:afcc516a22775a39d0d66f4c2ddc95d01be3e3d3862b21fcf4f9de34b4ad4e12
USER root
RUN python -c 'import runpy; assert runpy.run_path("/label-studio/label_studio/core/version_.py")["info"]["commit"] == "df96d79183156e556d91825d15fa7721f1145e1a"'
COPY deploy/oidc/requirements.lock /tmp/bridge-requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes --no-deps -r /tmp/bridge-requirements.lock && python -m pip check
COPY --chown=1001:0 label_studio/verdant_ls /label-studio/label_studio/verdant_ls
COPY --chown=1001:0 label_studio/templates/base.html /label-studio/label_studio/templates/base.html
COPY --chown=1001:0 label_studio/core/settings/label_studio.py /label-studio/label_studio/core/settings/label_studio.py
COPY --chown=1001:0 label_studio/tasks/serializers.py /label-studio/label_studio/tasks/serializers.py
COPY --chown=1001:0 label_studio/users/templates/users/user_account.html /label-studio/label_studio/users/templates/users/user_account.html
COPY --chown=1001:0 label_studio/verdant_ls/static/verdant_ls /label-studio/label_studio/core/static_build/verdant_ls
COPY --chown=1001:0 --from=frontend-builder /label-studio/web/dist /label-studio/web/dist
COPY --chown=1001:0 deploy/oidc/uwsgi.ini /label-studio/deploy/oidc-uwsgi.ini
COPY LICENSE NOTICE /label-studio/
ARG FORK_REVISION
RUN python -c 'import os,re; from pathlib import Path; sha=os.environ["FORK_REVISION"]; assert re.fullmatch("[0-9a-f]{40}",sha); Path("/label-studio/label_studio/core/version_.py").write_text("info = "+repr({"commit":sha,"version":"1.23.2+oidc","message":"Community OIDC candidate","branch":"downstream","date":""})+"\n")'
LABEL org.opencontainers.image.revision=$FORK_REVISION \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="heartexlabs/label-studio:1.23.2" \
      org.labelstudio.upstream.revision="df96d79183156e556d91825d15fa7721f1145e1a"
ENV DJANGO_SETTINGS_MODULE=verdant_ls.settings \
    PYTHONPATH=/label-studio/label_studio:/label-studio \
    SENTRY_DSN="" FRONTEND_SENTRY_DSN="" COLLECT_ANALYTICS=0
USER 1001
# No stock auto-bootstrap or startup migrations. Release job owns migration.
ENTRYPOINT []
CMD ["uwsgi", "--ini", "/label-studio/deploy/oidc-uwsgi.ini"]
