# ==============================================================================
# Gemfile — bamr87 portfolio site (zer0-mistakes remote theme)
# ==============================================================================
# Mirrors the theme's "github-pages" build environment so local previews match
# what GitHub Pages would produce. The github-pages gem bundles Jekyll 3.x plus
# the whitelisted plugins (jekyll-remote-theme, jekyll-feed, jekyll-sitemap,
# jekyll-seo-tag, jekyll-paginate, jekyll-relative-links, jekyll-redirect-from,
# jekyll-include-cache). Mermaid renders client-side via the theme's vendored JS,
# so no jekyll-mermaid gem is needed here.
# ==============================================================================

source "https://rubygems.org"

# GitHub Pages gem — includes Jekyll 3.x + the whitelisted plugins above.
gem "github-pages", ">= 228", group: :jekyll_plugins

# Web server for Ruby 3.0+ (WEBrick was removed from the standard library).
gem "webrick"

# Quiets a jekyll-remote-theme / Faraday warning on newer Ruby.
gem "faraday-retry"

# Platform-specific timezone + directory-watching support.
platforms :windows, :jruby do
  gem "tzinfo"
  gem "tzinfo-data"
end
gem "wdm", platforms: [:windows]
