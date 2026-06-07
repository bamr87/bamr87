# =============================================================================
# dash/Dockerfile — serves the central dashboard Jekyll site.
# =============================================================================
# GitHub Pages compatible toolchain (matches Gemfile: github-pages +
# jekyll-remote-theme). Gems install into /usr/local/bundle, which the
# compose file persists in a named volume, so the source tree can be
# bind-mounted for live editing without clobbering installed gems.
# =============================================================================
FROM ruby:3.3-bookworm

# build-essential: native extensions (ffi, nokogiri, eventmachine for livereload)
# git: required by jekyll-remote-theme to fetch bamr87/zer0-mistakes
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git \
 && rm -rf /var/lib/apt/lists/* \
 && gem install bundler

WORKDIR /site

EXPOSE 4000 35729

# Install/refresh gems against the mounted Gemfile, then serve with the
# dev config layered on top of production config and livereload enabled.
CMD bundle install \
 && bundle exec jekyll serve \
      --host 0.0.0.0 \
      --config _config.yml,_config_dev.yml \
      --livereload \
      --force_polling
