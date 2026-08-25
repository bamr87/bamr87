# Rakefile — root bamr87 dash site.
#
# This repo is a Jekyll site, not a tested Ruby library, so it has no unit suite.
# The unified CI ruby job runs `rake test`; this task is a fast, deterministic
# smoke test of the files that would break the dash if malformed (the Jekyll
# config and the project registry). A full build is covered by build-dash.yml.

require "yaml"

# _config.yml uses YAML anchors/aliases. Psych 4 (Ruby 3.1+) disables aliases by
# default and restricts classes; Psych 3 (Ruby 2.6) does neither. These are our
# own trusted files, so load them fully on whichever Psych is present.
def load_yaml(path)
  YAML.respond_to?(:unsafe_load_file) ? YAML.unsafe_load_file(path) : YAML.load_file(path)
end

desc "Lightweight sanity check: the dash's critical config files parse"
task :test do
  ["_config.yml", "_config_dev.yml", "_data/projects.yml"].each do |f|
    next unless File.exist?(f)
    load_yaml(f)
    puts "OK  #{f} parses"
  end

  reg = load_yaml("_data/projects.yml") || []
  raise "registry is empty" if reg.empty?
  missing = reg.reject { |p| p["name"] && p["branch"] && p["repo_url"] }
  raise "registry entries missing required keys: #{missing.map { |p| p['name'] }.inspect}" unless missing.empty?
  puts "OK  registry: #{reg.size} projects, required keys present"

  puts "dash sanity checks passed"
end

task default: :test
