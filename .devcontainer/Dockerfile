# ============================================================================
# bamr87 Monorepo - Development Container
# ============================================================================
#
# Node.js, Python, Ruby and shell tooling in one workspace image.
#
# Every base image below is an OFFICIAL language image, so its version flows
# from one place: `_data/fleet.yml` `images:` (rewritten by
# tools/docker_harmonize.py, gated by drift check (n)). An earlier revision was
# Ubuntu 22.04 with Ruby compiled from a source tarball — ~10 minutes of
# `make`, a hand-maintained RUBY_VERSION, and a Node/Python/Ruby trio that each
# had its own upgrade story.
#
# Ruby is 3.4, NOT 4.0: the github-pages gem the dash site builds with declares
# `Ruby >= 2.6, < 4.0`, so 4.0 cannot resolve it (see fleet.yml `images:`).

# Declared BEFORE the first FROM so it is visible to every FROM below — an ARG
# after a FROM belongs to that stage only, and `FROM ruby:${RUBY_VERSION}-trixie`
# would silently expand to `ruby:-trixie`.
ARG RUBY_VERSION=3.4

# ---------------------------------------------------------------------------
# Node.js — donor stage. Only the runtime is copied out; the version is the
# FROM tag, so `docker_harmonize.py` bumps it like any other image.
# ---------------------------------------------------------------------------
FROM node:24-trixie-slim AS node

# ---------------------------------------------------------------------------
# Development image: Ruby 3.4 on Debian 13 (trixie), which already carries the
# compiler toolchain, git and bundler.
# ---------------------------------------------------------------------------
FROM ruby:${RUBY_VERSION}-trixie AS development

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    gnupg \
    jq \
    less \
    openssh-client \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    shellcheck \
    sudo \
    unzip \
    vim \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Node runtime + npm/npx from the donor stage.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack

# Python tooling lives in its own venv on PATH. Debian 13 enforces PEP 668, so a
# bare `pip3 install` is refused — and a venv is what the fleet's own tools want
# anyway (PyYAML is the one every hub script imports).
ENV VIRTUAL_ENV=/opt/tools
ENV PATH=/opt/tools/bin:${PATH}
RUN python3 -m venv "${VIRTUAL_ENV}" \
    && "${VIRTUAL_ENV}/bin/pip" install --no-cache-dir \
        black \
        flake8 \
        mkdocs \
        mkdocs-material \
        pre-commit \
        pyyaml \
    && ln -sf "${VIRTUAL_ENV}/bin/python" /usr/local/bin/python

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} -m ${USERNAME} -s /bin/bash \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME}

# Set up workspace directory
RUN mkdir -p /workspace && chown ${USERNAME}:${USERNAME} /workspace

# Named-volume mount points nested under the /workspace bind mount. Docker
# seeds a fresh named volume from the IMAGE directory at that path, so these
# must exist here and be owned by the non-root user — otherwise Docker creates
# them root-owned on first mount and the container (uid 1000) cannot write to
# them. That is what left `console` in a restart loop ("Permission denied:
# /workspace/.venv-console/include") while `bundle-gems`, pre-created below,
# worked fine. Keep in sync with the volume list in docker-compose.yml.
RUN mkdir -p /workspace/.venv-console \
             /workspace/.venv-docs \
             /workspace/projects/README/.venv \
             /workspace/projects/cv-builder-pro/node_modules \
    && chown -R ${USERNAME}:${USERNAME} /workspace

# Gems install here (not under /usr/local, which root owns) so `bundle install`
# works as the non-root user. Backed by the `bundle-gems` named volume in
# docker-compose.yml — Docker seeds a fresh volume from this image directory,
# so ownership carries over on first mount.
ENV BUNDLE_PATH=/home/${USERNAME}/.bundle-gems
ENV BUNDLE_APP_CONFIG=/home/${USERNAME}/.bundle-gems
RUN mkdir -p "${BUNDLE_PATH}" && chown ${USERNAME}:${USERNAME} "${BUNDLE_PATH}"

# Version labels
LABEL maintainer="bamr87"
LABEL description="bamr87 monorepo development container"
LABEL org.opencontainers.image.source="https://github.com/bamr87/bamr87"

# Switch to non-root user
USER ${USERNAME}
WORKDIR /workspace

# Verify installations
RUN echo "=== Development Container Versions ===" \
    && echo "Node.js: $(node --version)" \
    && echo "npm:     $(npm --version)" \
    && echo "Python:  $(python3 --version)" \
    && echo "pip:     $(pip --version)" \
    && echo "git:     $(git --version)" \
    && echo "gh:      $(gh --version | head -1)" \
    && echo "Ruby:    $(ruby --version)" \
    && echo "Bundler: $(bundle --version)" \
    && echo "jq:      $(jq --version)" \
    && echo "shellcheck: $(shellcheck --version | head -2 | tail -1)"

CMD ["sleep", "infinity"]
