# Fleet logging for __PROJECT_NAME__ (Rails) — kit: elk v__KIT_VERSION__
#
# config/initializers/fleet_logging.rb
#
# Rails' default log is multi-line and unparseable as data: one request becomes
# six lines with no shared key. lograge collapses it to one line per request,
# which is what UPS-OPS-11 asks for and what the log plane can actually index.
#
#     gem "lograge"
#
require "json"

# Credential shapes from _data/fleet.yml `observability.logs.redact`. Applied at
# emission so it still holds when this repo runs standalone, without the hub's
# central Logstash filter in the path.
FLEET_REDACTIONS = [
  [/sk-ant-[A-Za-z0-9_\-]+/, "sk-ant-[REDACTED]"],
  [/github_pat_[A-Za-z0-9_]+/, "github_pat_[REDACTED]"],
  [/gh[pousr]_[A-Za-z0-9]{20,}/, "gh?_[REDACTED]"],
  [/AIza[A-Za-z0-9_\-]{20,}/, "AIza[REDACTED]"]
].freeze

def fleet_scrub(text)
  FLEET_REDACTIONS.reduce(text.to_s) { |acc, (rx, repl)| acc.gsub(rx, repl) }
end

Rails.application.configure do
  json = ENV.fetch("LOG_FORMAT", Rails.env.production? ? "json" : "text") == "json"

  config.lograge.enabled = true
  config.lograge.formatter = Lograge::Formatters::Json.new if json
  # Health endpoints are the majority of the traffic and none of the
  # information (UPS-OPS-11).
  config.lograge.ignore_actions = %w[HealthController#show Rails::HealthController#show]

  config.lograge.custom_options = lambda do |event|
    {
      ts: Time.now.utc.iso8601(3),
      app: ENV.fetch("APP_NAME", "__PROJECT_NAME__"),
      version: ENV.fetch("GIT_SHA", "dev"),
      request_id: event.payload[:request_id],
      level: event.payload[:exception] ? "error" : "info",
      msg: fleet_scrub("#{event.payload[:method]} #{event.payload[:path]}"),
      logger: "rails.request"
    }
  end

  config.logger = ActiveSupport::Logger.new($stdout)
  config.log_level = ENV.fetch("LOG_LEVEL", "info").downcase.to_sym
end
