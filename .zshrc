eval "$(gh copilot alias -- zsh)"

# Docker Aliases - Added on 2025-08-31
# Based on most frequently used commands from history

# Docker Compose shortcuts
alias dcu='docker-compose up'                    # Most used: docker-compose up
alias dcub='docker-compose up --build'          # Second most used: docker-compose up --build
alias dcd='docker-compose down'                  # Stop and remove containers
alias dcr='docker-compose restart'               # Restart services
alias dcps='docker-compose ps'                   # Show running containers
alias dcl='docker-compose logs'                  # Show logs
alias dclf='docker-compose logs -f'              # Follow logs

# Specific service shortcuts (based on your usage)
alias dcuj='docker-compose up jekyll'            # Start Jekyll service
alias dcrj='docker-compose restart jekyll'       # Restart Jekyll (most used restart)
alias dcra='docker-compose restart api'          # Restart API service
alias dclj='docker-compose logs jekyll'          # Jekyll logs
alias dcla='docker-compose logs api'             # API logs

# Detached mode shortcuts
alias dcud='docker-compose up -d'                # Start in background
alias dcudf='docker-compose up -d frontend'      # Start frontend in background

# Log tailing shortcuts (based on your patterns)
alias dclj20='docker-compose logs jekyll --tail=20'
alias dclj50='docker-compose logs jekyll --tail=50'
alias dcla5='docker-compose logs --tail=5 api'
alias dclf10='docker compose logs frontend --tail=10'

# Docker shortcuts
alias db='docker build'                          # Build image
alias dr='docker run'                            # Run container
alias dri='docker run -it'                       # Run interactive
alias drm='docker run --rm'                      # Run and remove
alias dp='docker ps'                             # List containers
alias dpa='docker ps -a'                         # List all containers
alias di='docker images'                         # List images
alias dex='docker exec'                          # Execute in container
alias dexi='docker exec -it'                     # Execute interactive

# Combined shortcuts for common workflows
alias dcupb='docker-compose up --build'          # Up with build
alias dcdcu='docker-compose down && docker-compose up'  # Restart all services
alias dclfc='docker-compose logs -f --tail=100'  # Follow logs with context

# Docker system management
alias dprune='docker system prune -f'            # Remove unused data
alias dprunea='docker system prune -a -f'        # Remove all unused data
alias dvprune='docker volume prune -f'           # Remove unused volumes
alias dnprune='docker network prune -f'          # Remove unused networks


# Created by `pipx` on 2025-10-29 03:00:38
export PATH="$PATH:/Users/bamr87/.local/bin"
