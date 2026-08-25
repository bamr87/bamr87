# ============================================================================
# bamr87 Monorepo - Development Container
# ============================================================================
#
# Multi-stage Dockerfile for the development environment.
# Provides Node.js, Python, Ruby, and shell tooling in a single container.
#

# ---------------------------------------------------------------------------
# Base image with common system dependencies
# ---------------------------------------------------------------------------
FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    ca-certificates \
    curl \
    git \
    gnupg \
    jq \
    less \
    lsb-release \
    openssh-client \
    shellcheck \
    sudo \
    unzip \
    wget \
    vim \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Node.js (LTS)
# ---------------------------------------------------------------------------
FROM base AS node-setup

RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g npm@latest \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Python 3.12
# ---------------------------------------------------------------------------
FROM node-setup AS python-setup

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Install common Python tools globally
# (Ubuntu 22.04 ships pip 22.0.2, which predates PEP 668 / --break-system-packages)
RUN pip3 install --no-cache-dir \
    pre-commit \
    black \
    flake8 \
    mkdocs \
    mkdocs-material

# ---------------------------------------------------------------------------
# Ruby 3.3 (matches build-dash.yml's ruby/setup-ruby version)
# ---------------------------------------------------------------------------
# Ubuntu 22.04 (jammy) has no apt package for Ruby 3.3 — the archive ships 3.0,
# and the brightbox PPA that used to backport newer Rubies stopped publishing
# jammy builds after 2.7. Build from the official source tarball instead; the
# root Gemfile (github-pages + jekyll) needs the dash's Jekyll site to build.
FROM python-setup AS ruby-setup

ARG RUBY_VERSION=3.3.11

RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf \
    bison \
    libffi-dev \
    libgdbm-dev \
    libgmp-dev \
    libncurses-dev \
    libreadline-dev \
    libssl-dev \
    libyaml-dev \
    uuid-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://cache.ruby-lang.org/pub/ruby/${RUBY_VERSION%.*}/ruby-${RUBY_VERSION}.tar.gz" -o /tmp/ruby.tar.gz \
    && tar -xzf /tmp/ruby.tar.gz -C /tmp \
    && cd "/tmp/ruby-${RUBY_VERSION}" \
    && ./configure --disable-install-doc --prefix=/usr/local \
    && make -j"$(nproc)" \
    && make install \
    && cd / && rm -rf "/tmp/ruby-${RUBY_VERSION}" /tmp/ruby.tar.gz \
    && gem install bundler --no-document

# ---------------------------------------------------------------------------
# GitHub CLI
# ---------------------------------------------------------------------------
FROM ruby-setup AS gh-setup

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Final development image
# ---------------------------------------------------------------------------
FROM gh-setup AS development

# Create non-root user
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} -m ${USERNAME} -s /bin/bash \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME}

# Set up workspace directory
RUN mkdir -p /workspace && chown ${USERNAME}:${USERNAME} /workspace

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
    && echo "pip:     $(pip3 --version)" \
    && echo "git:     $(git --version)" \
    && echo "gh:      $(gh --version | head -1)" \
    && echo "Ruby:    $(ruby --version)" \
    && echo "Bundler: $(bundle --version)" \
    && echo "jq:      $(jq --version)" \
    && echo "shellcheck: $(shellcheck --version | head -2 | tail -1)"

CMD ["sleep", "infinity"]
