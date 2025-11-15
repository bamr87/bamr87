---
applyTo: '**/*.sh,**/*.bash,scripts/**/*'
---

# Bash Scripting Standards

Comprehensive bash scripting standards including styling, documentation, error handling, and best practices. This guide ensures scripts are robust, maintainable, and production-ready across all project types.

## Script Template

Every bash script should follow this comprehensive template:

```bash
#!/bin/bash
#
# File: script-name.sh
# Description: One-line description of what this script does
# Version: 1.0.0
# Author: Name <email@example.com>
# Created: YYYY-MM-DD
# Last Modified: YYYY-MM-DD
#
# Usage: ./script-name.sh [OPTIONS] [ARGUMENTS]
#   OPTIONS:
#     -h, --help          Display this help message
#     -v, --verbose       Enable verbose output
#     -d, --dry-run       Preview actions without executing
#     -q, --quiet         Suppress non-error output
#
# Examples:
#   ./script-name.sh --verbose input.txt
#   ./script-name.sh --dry-run --quiet
#
# Exit Codes:
#   0 - Success
#   1 - General error
#   2 - Misuse of command (invalid arguments)
#   3 - Configuration error
#   4 - Resource not found
#   5 - Permission denied
#
# Dependencies:
#   - jq (for JSON processing)
#   - curl (for HTTP requests)
#
# Environment Variables:
#   API_KEY       - API authentication key (required)
#   LOG_LEVEL     - Logging verbosity: DEBUG|INFO|WARN|ERROR (default: INFO)
#   TIMEOUT       - Operation timeout in seconds (default: 30)
#
# Notes:
#   - Requires bash 4.0 or higher
#   - Tested on macOS 12+ and Ubuntu 20.04+
#

# ============================================================================
# INITIALIZATION AND CONFIGURATION
# ============================================================================

# Exit immediately on error, undefined variables, and pipe failures (DFF)
set -euo pipefail

# Enable debug mode if DEBUG environment variable is set
[[ "${DEBUG:-}" == "true" ]] && set -x

# Script metadata
readonly SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../" && pwd)"
readonly SCRIPT_VERSION="1.0.0"

# Configuration with defaults
readonly DEFAULT_TIMEOUT=30
readonly DEFAULT_LOG_LEVEL="INFO"
readonly MAX_RETRIES=3

# Runtime configuration (can be overridden by flags)
VERBOSE="${VERBOSE:-false}"
DRY_RUN="${DRY_RUN:-false}"
QUIET="${QUIET:-false}"
TIMEOUT="${TIMEOUT:-$DEFAULT_TIMEOUT}"
LOG_LEVEL="${LOG_LEVEL:-$DEFAULT_LOG_LEVEL}"

# Log file location
readonly LOG_DIR="${PROJECT_ROOT}/logs"
readonly LOG_FILE="${LOG_DIR}/${SCRIPT_NAME%.sh}-$(date +%Y%m%d-%H%M%S).log"

# Colors for output (use only when outputting to terminal)
if [[ -t 1 ]]; then
    readonly RED='\033[0;31m'
    readonly GREEN='\033[0;32m'
    readonly YELLOW='\033[1;33m'
    readonly BLUE='\033[0;34m'
    readonly MAGENTA='\033[0;35m'
    readonly CYAN='\033[0;36m'
    readonly BOLD='\033[1m'
    readonly NC='\033[0m'  # No Color
else
    readonly RED=''
    readonly GREEN=''
    readonly YELLOW=''
    readonly BLUE=''
    readonly MAGENTA=''
    readonly CYAN=''
    readonly BOLD=''
    readonly NC=''
fi

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

#######################################
# Display usage information and exit
# Globals:
#   SCRIPT_NAME
# Arguments:
#   None
# Outputs:
#   Writes usage information to stdout
# Returns:
#   Exits with code 0
#######################################
usage() {
    cat <<EOF
${BOLD}Usage:${NC} ${SCRIPT_NAME} [OPTIONS] [ARGUMENTS]

${BOLD}Description:${NC}
  Detailed description of what this script does, including any important
  context or background information that users should know.

${BOLD}Options:${NC}
  -h, --help              Display this help message and exit
  -v, --verbose           Enable verbose output for debugging
  -d, --dry-run           Preview actions without making changes
  -q, --quiet             Suppress non-error output
  -t, --timeout SECONDS   Set operation timeout (default: ${DEFAULT_TIMEOUT})

${BOLD}Arguments:${NC}
  FILE                    Input file to process
  DIRECTORY               Target directory for operation

${BOLD}Examples:${NC}
  # Basic usage
  ${SCRIPT_NAME} input.txt

  # Verbose mode with custom timeout
  ${SCRIPT_NAME} --verbose --timeout 60 input.txt

  # Dry run to preview actions
  ${SCRIPT_NAME} --dry-run directory/

${BOLD}Environment Variables:${NC}
  API_KEY                 API authentication key (required)
  LOG_LEVEL               Logging level: DEBUG|INFO|WARN|ERROR (default: INFO)
  TIMEOUT                 Default timeout in seconds (default: ${DEFAULT_TIMEOUT})

${BOLD}Exit Codes:${NC}
  0                       Success
  1                       General error
  2                       Invalid arguments
  3                       Configuration error
  4                       Resource not found
  5                       Permission denied

${BOLD}For more information:${NC}
  Project documentation: https://github.com/user/repo
  Issue tracker: https://github.com/user/repo/issues

EOF
    exit 0
}

# ============================================================================
# LOGGING FUNCTIONS
# ============================================================================

#######################################
# Initialize logging system
# Creates log directory and configures log file
# Globals:
#   LOG_DIR, LOG_FILE
# Arguments:
#   None
# Returns:
#   0 on success, 1 on failure
#######################################
init_logging() {
    # Create log directory if it doesn't exist
    if [[ ! -d "$LOG_DIR" ]]; then
        mkdir -p "$LOG_DIR" || {
            echo "ERROR: Failed to create log directory: $LOG_DIR" >&2
            return 1
        }
    fi
    
    # Initialize log file
    {
        echo "========================================="
        echo "Script: $SCRIPT_NAME"
        echo "Version: $SCRIPT_VERSION"
        echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "User: ${USER}"
        echo "Host: ${HOSTNAME}"
        echo "PID: $$"
        echo "========================================="
    } > "$LOG_FILE"
    
    return 0
}

#######################################
# Log message with level and timestamp
# Writes to both stdout/stderr and log file
# Globals:
#   LOG_FILE, LOG_LEVEL, QUIET, colors
# Arguments:
#   $1 - Log level (DEBUG|INFO|WARN|ERROR)
#   $2 - Message to log
# Outputs:
#   Writes formatted message to stdout/stderr and log file
#######################################
log() {
    local level="$1"
    local message="$2"
    local timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local log_entry="[${level}] ${timestamp} - ${message}"
    
    # Write to log file (always)
    echo "$log_entry" >> "$LOG_FILE"
    
    # Check if level should be displayed
    case "$LOG_LEVEL" in
        DEBUG)
            # Show all levels
            ;;
        INFO)
            [[ "$level" == "DEBUG" ]] && return 0
            ;;
        WARN)
            [[ "$level" =~ ^(DEBUG|INFO)$ ]] && return 0
            ;;
        ERROR)
            [[ "$level" != "ERROR" ]] && return 0
            ;;
    esac
    
    # Skip console output if quiet mode (except errors)
    [[ "$QUIET" == "true" && "$level" != "ERROR" ]] && return 0
    
    # Write to console with colors
    case "$level" in
        DEBUG)
            echo -e "${CYAN}[DEBUG]${NC} ${timestamp} - ${message}"
            ;;
        INFO)
            echo -e "${GREEN}[INFO]${NC} ${timestamp} - ${message}"
            ;;
        WARN)
            echo -e "${YELLOW}[WARN]${NC} ${timestamp} - ${message}"
            ;;
        ERROR)
            echo -e "${RED}[ERROR]${NC} ${timestamp} - ${message}" >&2
            ;;
    esac
}

#######################################
# Convenience logging functions
# Wrappers around log() for specific levels
#######################################
log_debug() { log "DEBUG" "$1"; }
log_info() { log "INFO" "$1"; }
log_warn() { log "WARN" "$1"; }
log_error() { log "ERROR" "$1"; }

# ============================================================================
# ERROR HANDLING AND CLEANUP (DFF)
# ============================================================================

#######################################
# Handle script errors and perform cleanup
# Called automatically via ERR trap
# Globals:
#   LINENO (bash built-in), BASH_SOURCE, BASH_LINENO
# Arguments:
#   $1 - Line number where error occurred
#   $2 - Exit code (optional)
# Returns:
#   Exits with provided code or 1
#######################################
error_handler() {
    local line_number="${1:-unknown}"
    local exit_code="${2:-1}"
    local last_command="${BASH_COMMAND}"
    
    log_error "Script failed at line ${line_number}"
    log_error "Failed command: ${last_command}"
    log_error "Exit code: ${exit_code}"
    
    # Show call stack
    log_error "Call stack:"
    local frame=0
    while caller $frame; do
        ((frame++))
    done | while read line func file; do
        log_error "  at ${func} (${file}:${line})"
    done
    
    # Perform cleanup
    cleanup_on_error
    
    exit "$exit_code"
}

# Set trap for errors (calls error_handler on any error)
trap 'error_handler ${LINENO} $?' ERR

#######################################
# Cleanup on script exit (normal or error)
# Called via EXIT trap
# Globals:
#   Various temporary files/resources
# Arguments:
#   None
#######################################
cleanup() {
    local exit_code=$?
    
    log_debug "Performing cleanup (exit code: ${exit_code})"
    
    # Remove temporary files
    if [[ -n "${TEMP_FILE:-}" && -f "$TEMP_FILE" ]]; then
        rm -f "$TEMP_FILE"
        log_debug "Removed temporary file: $TEMP_FILE"
    fi
    
    # Clean up temporary directory
    if [[ -n "${TEMP_DIR:-}" && -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
        log_debug "Removed temporary directory: $TEMP_DIR"
    fi
    
    # Kill background processes
    if [[ -n "${BG_PID:-}" ]]; then
        kill "$BG_PID" 2>/dev/null || true
        log_debug "Terminated background process: $BG_PID"
    fi
    
    if [[ $exit_code -eq 0 ]]; then
        log_info "Script completed successfully"
    else
        log_error "Script completed with errors (exit code: ${exit_code})"
    fi
    
    log_info "Log saved to: $LOG_FILE"
}

# Set trap for script exit
trap cleanup EXIT

#######################################
# Cleanup after error
# Called by error_handler before exit
# Globals:
#   Various resources that need cleanup
# Arguments:
#   None
#######################################
cleanup_on_error() {
    log_warn "Performing error cleanup..."
    
    # Rollback changes if needed
    if [[ "${CHANGES_MADE:-false}" == "true" ]]; then
        log_warn "Attempting to rollback changes..."
        rollback_changes || log_error "Rollback failed"
    fi
    
    # Release locks
    if [[ -f "${LOCK_FILE:-}" ]]; then
        rm -f "$LOCK_FILE"
        log_debug "Released lock file"
    fi
}

#######################################
# Signal handler for graceful termination
# Handles SIGINT (Ctrl+C) and SIGTERM
# Arguments:
#   $1 - Signal name
#######################################
signal_handler() {
    local signal="$1"
    log_warn "Received ${signal} signal"
    log_info "Shutting down gracefully..."
    exit 130  # Standard exit code for SIGINT
}

# Set trap for signals
trap 'signal_handler SIGINT' INT
trap 'signal_handler SIGTERM' TERM

# ============================================================================
# VALIDATION AND PREREQUISITES
# ============================================================================

#######################################
# Validate script prerequisites
# Checks for required tools, permissions, and configurations
# Globals:
#   Various configuration variables
# Arguments:
#   None
# Returns:
#   0 on success, 1 on failure
#######################################
validate_prerequisites() {
    log_info "Validating prerequisites..."
    
    # Check bash version
    if [[ "${BASH_VERSINFO[0]}" -lt 4 ]]; then
        log_error "Bash 4.0 or higher required (current: ${BASH_VERSION})"
        return 1
    fi
    
    # Check required commands
    local required_commands=("git" "curl" "jq")
    local missing_commands=()
    
    for cmd in "${required_commands[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            missing_commands+=("$cmd")
        fi
    done
    
    if [[ ${#missing_commands[@]} -gt 0 ]]; then
        log_error "Missing required commands: ${missing_commands[*]}"
        log_error "Install with: apt-get install ${missing_commands[*]} (Ubuntu/Debian)"
        log_error "Or: brew install ${missing_commands[*]} (macOS)"
        return 1
    fi
    
    # Check required environment variables
    if [[ -z "${API_KEY:-}" ]]; then
        log_error "Required environment variable API_KEY is not set"
        log_error "Set with: export API_KEY='your-api-key'"
        return 1
    fi
    
    # Check write permissions to required directories
    local required_dirs=("$LOG_DIR" "${PROJECT_ROOT}/output")
    for dir in "${required_dirs[@]}"; do
        if [[ ! -w "$dir" ]] && [[ ! -w "$(dirname "$dir")" ]]; then
            log_error "No write permission for directory: $dir"
            return 1
        fi
    done
    
    log_info "All prerequisites validated successfully"
    return 0
}

#######################################
# Validate input arguments
# Checks that required arguments are provided and valid
# Arguments:
#   $@ - All script arguments to validate
# Returns:
#   0 if valid, 1 if invalid
#######################################
validate_arguments() {
    log_debug "Validating arguments: $*"
    
    # Example: Check file exists
    if [[ $# -lt 1 ]]; then
        log_error "Missing required argument: FILE"
        usage
    fi
    
    local input_file="$1"
    
    if [[ ! -f "$input_file" ]]; then
        log_error "Input file not found: $input_file"
        return 1
    fi
    
    if [[ ! -r "$input_file" ]]; then
        log_error "Cannot read input file: $input_file"
        return 1
    fi
    
    log_debug "Arguments validated successfully"
    return 0
}

# ============================================================================
# HELPER FUNCTIONS (DRY: Reusable utilities)
# ============================================================================

#######################################
# Check if command exists
# Arguments:
#   $1 - Command name to check
# Returns:
#   0 if exists, 1 if not found
#######################################
command_exists() {
    command -v "$1" &> /dev/null
}

#######################################
# Prompt user for confirmation
# Arguments:
#   $1 - Prompt message
#   $2 - Default answer (y/n, optional, default: n)
# Returns:
#   0 if yes, 1 if no
#######################################
confirm() {
    local prompt="$1"
    local default="${2:-n}"
    local response
    
    # Skip prompts in non-interactive mode or dry-run
    [[ "$DRY_RUN" == "true" ]] && return 0
    [[ ! -t 0 ]] && return 1  # Not interactive
    
    while true; do
        read -r -p "${prompt} [y/n] (default: ${default}): " response
        response="${response:-$default}"
        
        case "${response,,}" in  # Convert to lowercase
            y|yes)
                return 0
                ;;
            n|no)
                return 1
                ;;
            *)
                echo "Please answer yes or no"
                ;;
        esac
    done
}

#######################################
# Execute command with retry logic (DFF: handle transient failures)
# Arguments:
#   $@ - Command to execute
# Globals:
#   MAX_RETRIES
# Returns:
#   0 on success, 1 after all retries failed
#######################################
retry_command() {
    local attempt=1
    local exit_code=0
    
    while [[ $attempt -le $MAX_RETRIES ]]; do
        log_debug "Attempt ${attempt}/${MAX_RETRIES}: $*"
        
        if "$@"; then
            log_debug "Command succeeded on attempt ${attempt}"
            return 0
        fi
        
        exit_code=$?
        log_warn "Command failed on attempt ${attempt} with exit code ${exit_code}"
        
        if [[ $attempt -lt $MAX_RETRIES ]]; then
            local backoff=$((2 ** (attempt - 1)))  # Exponential backoff
            log_info "Retrying in ${backoff} seconds..."
            sleep "$backoff"
        fi
        
        ((attempt++))
    done
    
    log_error "Command failed after ${MAX_RETRIES} attempts: $*"
    return 1
}

#######################################
# Display progress spinner for long operations
# Arguments:
#   $1 - PID of process to monitor
#   $2 - Message to display
# Outputs:
#   Animated spinner to stdout
#######################################
show_spinner() {
    local pid=$1
    local message="${2:-Processing}"
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    
    [[ "$QUIET" == "true" ]] && return 0
    
    while kill -0 "$pid" 2>/dev/null; do
        i=$(( (i+1) % ${#spin} ))
        printf "\r${CYAN}%s${NC} %s" "${spin:$i:1}" "$message"
        sleep 0.1
    done
    
    printf "\r%*s\r" $((${#message} + 3)) ""  # Clear line
}

#######################################
# Show progress bar
# Arguments:
#   $1 - Current progress (0-100)
#   $2 - Message (optional)
#######################################
show_progress() {
    local progress=$1
    local message="${2:-Progress}"
    local bar_length=50
    local filled_length=$((progress * bar_length / 100))
    local bar=""
    
    [[ "$QUIET" == "true" ]] && return 0
    
    # Build progress bar
    for ((i=0; i<bar_length; i++)); do
        if [[ $i -lt $filled_length ]]; then
            bar+="█"
        else
            bar+="░"
        fi
    done
    
    printf "\r${message}: [${bar}] ${progress}%%"
    
    [[ $progress -eq 100 ]] && echo ""  # New line when complete
}

#######################################
# Safe file operations (DFF: check before operating)
#######################################

# Safe file read with validation
safe_read_file() {
    local file="$1"
    
    if [[ ! -f "$file" ]]; then
        log_error "File not found: $file"
        return 1
    fi
    
    if [[ ! -r "$file" ]]; then
        log_error "Cannot read file: $file"
        return 1
    fi
    
    cat "$file"
}

# Safe file write with backup
safe_write_file() {
    local file="$1"
    local content="$2"
    local backup_file="${file}.backup.$(date +%Y%m%d-%H%M%S)"
    
    # Backup existing file
    if [[ -f "$file" ]]; then
        cp "$file" "$backup_file" || {
            log_error "Failed to create backup: $backup_file"
            return 1
        }
        log_debug "Created backup: $backup_file"
    fi
    
    # Write new content
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] Would write to: $file"
        return 0
    fi
    
    echo "$content" > "$file" || {
        log_error "Failed to write file: $file"
        # Restore backup if write failed
        [[ -f "$backup_file" ]] && mv "$backup_file" "$file"
        return 1
    }
    
    log_info "Successfully wrote file: $file"
    return 0
}

# ============================================================================
# BUSINESS LOGIC FUNCTIONS
# ============================================================================

#######################################
# Main processing function
# Implements the core functionality of the script
# Arguments:
#   $1 - Input data or file
# Returns:
#   0 on success, non-zero on failure
#######################################
process_input() {
    local input="$1"
    
    log_info "Processing input: $input"
    
    # Validate input
    if [[ -z "$input" ]]; then
        log_error "Input cannot be empty"
        return 1
    fi
    
    # Show progress for long operation
    {
        # Actual processing logic here
        sleep 2  # Simulated work
        
    } &
    local pid=$!
    show_spinner "$pid" "Processing input"
    wait "$pid"
    
    log_info "Processing completed successfully"
    return 0
}

#######################################
# Example function with comprehensive documentation
# This function demonstrates all documentation standards
# Globals:
#   PROJECT_ROOT - Used for file path resolution
#   VERBOSE - Affects output detail level
# Arguments:
#   $1 - First argument description
#   $2 - Second argument description (optional)
# Outputs:
#   Writes results to stdout
#   Logs operations to LOG_FILE
# Returns:
#   0 on success
#   1 on general error
#   4 if resource not found
# Example:
#   example_function "input" "output"
#   example_function "input"  # Second arg optional
#######################################
example_function() {
    local first_arg="$1"
    local second_arg="${2:-default_value}"
    
    log_debug "Called ${FUNCNAME[0]} with args: $*"
    
    # Validate arguments
    if [[ -z "$first_arg" ]]; then
        log_error "${FUNCNAME[0]}: First argument is required"
        return 1
    fi
    
    # Business logic here
    log_info "Processing: $first_arg"
    
    if [[ "$VERBOSE" == "true" ]]; then
        log_info "Using second argument: $second_arg"
    fi
    
    # Return success
    return 0
}

# ============================================================================
# ARGUMENT PARSING
# ============================================================================

#######################################
# Parse command-line arguments
# Processes all flags and arguments, setting global variables
# Arguments:
#   $@ - All script arguments
# Globals:
#   Sets VERBOSE, DRY_RUN, QUIET, TIMEOUT, etc.
# Returns:
#   0 on success, exits on invalid arguments
#######################################
parse_arguments() {
    # Store positional arguments
    local positional_args=()
    
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                usage
                ;;
            
            -v|--verbose)
                VERBOSE=true
                LOG_LEVEL="DEBUG"
                log_debug "Verbose mode enabled"
                shift
                ;;
            
            -d|--dry-run)
                DRY_RUN=true
                log_info "Dry run mode enabled (no changes will be made)"
                shift
                ;;
            
            -q|--quiet)
                QUIET=true
                log_debug "Quiet mode enabled"
                shift
                ;;
            
            -t|--timeout)
                if [[ -n "${2:-}" ]]; then
                    TIMEOUT="$2"
                    log_debug "Timeout set to: ${TIMEOUT}s"
                    shift 2
                else
                    log_error "Option --timeout requires an argument"
                    exit 2
                fi
                ;;
            
            --version)
                echo "${SCRIPT_NAME} version ${SCRIPT_VERSION}"
                exit 0
                ;;
            
            --)
                # End of options marker
                shift
                positional_args+=("$@")
                break
                ;;
            
            -*)
                log_error "Unknown option: $1"
                echo "Try '${SCRIPT_NAME} --help' for more information"
                exit 2
                ;;
            
            *)
                # Positional argument
                positional_args+=("$1")
                shift
                ;;
        esac
    done
    
    # Restore positional arguments
    set -- "${positional_args[@]}"
    
    # Export for use in main
    POSITIONAL_ARGS=("$@")
    
    log_debug "Parsed ${#POSITIONAL_ARGS[@]} positional arguments"
    return 0
}

# ============================================================================
# MAIN FUNCTION
# ============================================================================

#######################################
# Main script entry point
# Orchestrates the script execution flow
# Arguments:
#   $@ - All command-line arguments
# Returns:
#   0 on success, non-zero on failure
#######################################
main() {
    log_info "Starting ${SCRIPT_NAME} v${SCRIPT_VERSION}"
    
    # Initialize logging
    init_logging || {
        echo "ERROR: Failed to initialize logging" >&2
        exit 1
    }
    
    # Parse command-line arguments
    parse_arguments "$@"
    
    # Validate prerequisites
    validate_prerequisites || {
        log_error "Prerequisites validation failed"
        exit 3
    }
    
    # Validate arguments
    validate_arguments "${POSITIONAL_ARGS[@]}" || {
        log_error "Argument validation failed"
        exit 2
    }
    
    log_info "Configuration:"
    log_info "  Verbose: $VERBOSE"
    log_info "  Dry Run: $DRY_RUN"
    log_info "  Timeout: ${TIMEOUT}s"
    log_info "  Log Level: $LOG_LEVEL"
    
    # Main processing
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "=== DRY RUN MODE - No changes will be made ==="
    fi
    
    # Execute main business logic
    process_input "${POSITIONAL_ARGS[0]}" || {
        log_error "Processing failed"
        exit 1
    }
    
    log_info "Script completed successfully"
    return 0
}

# ============================================================================
# SCRIPT EXECUTION
# ============================================================================

# Only execute main if script is run directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
```

## Styling Standards

### File Organization

Scripts should be organized in clear sections:

1. **Header Documentation** (lines 1-50)
   - Shebang
   - File information
   - Usage documentation
   - Examples and exit codes

2. **Initialization** (constants, configuration)
   - `set` commands
   - `readonly` constants
   - Default configuration values

3. **Utility Functions** (logging, validation, helpers)
   - Logging functions
   - Validation functions
   - Helper utilities

4. **Error Handling** (traps, cleanup)
   - Error handlers
   - Cleanup functions
   - Signal handlers

5. **Business Logic** (main functionality)
   - Core processing functions
   - Domain-specific logic

6. **Argument Parsing** (command-line interface)
   - Parse flags and options
   - Validate arguments

7. **Main Function** (orchestration)
   - Entry point
   - Workflow coordination

8. **Execution** (script invocation)
   - Main execution guard

### Naming Conventions

```bash
# Constants: UPPER_CASE with underscores
readonly MAX_RETRIES=3
readonly DEFAULT_TIMEOUT=30
readonly API_ENDPOINT="https://api.example.com"

# Variables: lowercase with underscores
local user_count=0
local input_file="data.txt"
local is_valid=false

# Functions: lowercase with underscores
function process_data() { }
function validate_input() { }
function send_notification() { }

# Private/internal functions: prefix with underscore
function _internal_helper() { }
function _parse_json() { }

# Boolean variables: use is_/has_/should_ prefix
local is_valid=false
local has_permission=true
local should_retry=true
```

### Indentation and Spacing

```bash
# Use 4 spaces for indentation (not tabs)
function example() {
    local var="value"
    
    if [[ condition ]]; then
        # 4 spaces
        command here
        
        if [[ nested ]]; then
            # 8 spaces
            nested command
        fi
    fi
}

# Blank lines for readability
function process() {
    # Group related operations
    local input="$1"
    local output=""
    
    # Blank line before new logical section
    validate_input "$input" || return 1
    
    # Blank line between major operations
    output=$(transform_input "$input")
    
    # Blank line before return
    echo "$output"
    return 0
}

# Align related assignments
readonly SHORT_VAR="value"
readonly LONGER_VARIABLE="value"
readonly VERY_LONG_VARIABLE_NAME="value"

# Or don't align if it hurts readability
readonly SHORT="value"
readonly MEDIUM_LENGTH="value"
readonly EXTRAORDINARILY_LONG_NAME="value"
```

### Quoting Rules

```bash
# Always quote variable expansions (prevents word splitting)
local file_path="/path/to/file with spaces.txt"
cat "$file_path"  # Correct
cat $file_path    # WRONG: breaks on spaces

# Quote command substitutions
local current_date="$(date +%Y-%m-%d)"  # Correct
local current_date=$(date +%Y-%m-%d)    # Works but inconsistent

# Quote arrays properly
local files=("file1.txt" "file with spaces.txt" "file3.txt")
for file in "${files[@]}"; do  # Correct: preserves spaces
    echo "$file"
done

# Don't quote when word splitting is desired (rare)
local options="-v -x -e"
command $options  # Intentionally unquoted to split into separate args

# Quote heredocs delimiter to prevent expansion
cat <<'EOF'
This $VARIABLE will not be expanded
EOF

# Don't quote heredoc delimiter to allow expansion
cat <<EOF
This $VARIABLE will be expanded to: ${VARIABLE}
EOF
```

### Conditionals and Tests

```bash
# Use [[ ]] for tests (more features than [ ])
if [[ "$var" == "value" ]]; then
    echo "Match"
fi

# String comparisons
[[ "$str1" == "$str2" ]]      # Equality
[[ "$str1" != "$str2" ]]      # Inequality
[[ "$str" =~ ^pattern$ ]]     # Regex match
[[ -z "$str" ]]               # Empty string
[[ -n "$str" ]]               # Non-empty string

# Numeric comparisons
[[ $num1 -eq $num2 ]]         # Equal
[[ $num1 -ne $num2 ]]         # Not equal
[[ $num1 -lt $num2 ]]         # Less than
[[ $num1 -le $num2 ]]         # Less than or equal
[[ $num1 -gt $num2 ]]         # Greater than
[[ $num1 -ge $num2 ]]         # Greater than or equal

# File tests
[[ -f "$file" ]]              # File exists
[[ -d "$dir" ]]               # Directory exists
[[ -r "$file" ]]              # Readable
[[ -w "$file" ]]              # Writable
[[ -x "$file" ]]              # Executable
[[ -s "$file" ]]              # Not empty
[[ ! -e "$path" ]]            # Does not exist

# Logical operators
[[ condition1 && condition2 ]]    # AND
[[ condition1 || condition2 ]]    # OR
[[ ! condition ]]                 # NOT

# Prefer separate if statements over complex conditions (KIS)
# Good: Clear and readable
if [[ ! -f "$file" ]]; then
    log_error "File not found: $file"
    return 1
fi

if [[ ! -r "$file" ]]; then
    log_error "Cannot read file: $file"
    return 1
fi

# Less clear: Combined condition
if [[ ! -f "$file" || ! -r "$file" ]]; then
    log_error "File error"
    return 1
fi
```

### Loops

```bash
# For loop with array
local files=("file1.txt" "file2.txt" "file3.txt")
for file in "${files[@]}"; do
    echo "Processing: $file"
done

# For loop with range
for i in {1..10}; do
    echo "Iteration $i"
done

# For loop with command output (avoid when possible, use while read)
# Less efficient:
for line in $(cat file.txt); do
    echo "$line"
done

# More efficient:
while IFS= read -r line; do
    echo "$line"
done < file.txt

# For loop with glob (safe with nullglob)
shopt -s nullglob  # Prevent literal expansion if no matches
for file in *.txt; do
    [[ -f "$file" ]] && echo "Found: $file"
done

# While loop
local count=0
while [[ $count -lt 10 ]]; do
    echo "Count: $count"
    ((count++))
done

# Until loop
local ready=false
until [[ "$ready" == true ]]; do
    check_status && ready=true || sleep 5
done

# C-style for loop
for ((i=0; i<10; i++)); do
    echo "Index: $i"
done
```

### Functions

```bash
# Function declaration (preferred: explicit function keyword)
function function_name() {
    local arg1="$1"
    local arg2="${2:-default}"
    
    # Function body
    return 0
}

# Alternative (works but less clear)
function_name() {
    # Body
}

# Function with comprehensive documentation
#######################################
# Process user data with validation
# Validates user input and performs processing with error handling.
# Implements DFF principle with comprehensive error checking.
# Globals:
#   DATABASE_URL - Database connection string
# Arguments:
#   $1 - User ID (required)
#   $2 - Action to perform (optional, default: "read")
# Outputs:
#   Writes processed data to stdout
#   Logs operations to LOG_FILE
# Returns:
#   0 - Success
#   1 - Invalid user ID
#   2 - Processing failed
#   4 - User not found
# Example:
#   process_user_data "user123" "update"
#######################################
function process_user_data() {
    local user_id="$1"
    local action="${2:-read}"
    
    # Validation
    [[ -z "$user_id" ]] && return 1
    
    # Processing
    log_info "Processing user: $user_id (action: $action)"
    
    # Implementation
    case "$action" in
        read)
            echo "Reading user $user_id"
            ;;
        update)
            echo "Updating user $user_id"
            ;;
        delete)
            echo "Deleting user $user_id"
            ;;
        *)
            log_error "Unknown action: $action"
            return 2
            ;;
    esac
    
    return 0
}

# Return vs Exit
# Use return in functions, exit in main script
function my_function() {
    [[ condition ]] && return 1  # Return from function
    return 0
}

# In main script or error handler
[[ condition ]] && exit 1  # Exit entire script
```

### Arrays

```bash
# Array declaration
local simple_array=("item1" "item2" "item3")
local files=(*.txt)
local empty_array=()

# Array operations
simple_array+=("item4")              # Append
echo "${simple_array[0]}"            # First element
echo "${simple_array[@]}"            # All elements
echo "${#simple_array[@]}"           # Length
echo "${simple_array[@]:1:2}"        # Slice: elements 1-2

# Iterate array properly (preserves spaces)
for item in "${simple_array[@]}"; do
    echo "Item: $item"
done

# Check if array is empty
if [[ ${#simple_array[@]} -eq 0 ]]; then
    echo "Array is empty"
fi

# Associative arrays (bash 4+)
declare -A config=(
    [host]="localhost"
    [port]="8080"
    [timeout]="30"
)

echo "${config[host]}"      # Access value
echo "${!config[@]}"        # All keys
echo "${config[@]}"         # All values

# Iterate associative array
for key in "${!config[@]}"; do
    echo "$key = ${config[$key]}"
done
```

## Error Handling Best Practices (DFF)

### Set Options

```bash
# Essential error handling (always use these)
set -e  # Exit on error
set -u  # Exit on undefined variable
set -o pipefail  # Pipe failures cause exit

# Combined:
set -euo pipefail

# Debug mode (optional)
set -x  # Print commands before executing

# Safer arithmetic
set +u  # Temporarily disable
count=${count:-0}  # Set default
((count++)) || true  # Prevent exit on arithmetic error
set -u  # Re-enable
```

### Error Codes

```bash
# Standard exit codes
readonly EXIT_SUCCESS=0
readonly EXIT_GENERAL_ERROR=1
readonly EXIT_MISUSE=2           # Invalid arguments
readonly EXIT_CONFIG_ERROR=3
readonly EXIT_NOT_FOUND=4
readonly EXIT_PERMISSION_DENIED=5
readonly EXIT_TIMEOUT=124
readonly EXIT_SIGNAL=128         # Base for signals (128 + signal_number)

# Use meaningful exit codes
function check_file() {
    local file="$1"
    
    if [[ ! -e "$file" ]]; then
        log_error "File not found: $file"
        return $EXIT_NOT_FOUND
    fi
    
    if [[ ! -r "$file" ]]; then
        log_error "Permission denied: $file"
        return $EXIT_PERMISSION_DENIED
    fi
    
    return $EXIT_SUCCESS
}

# Handle specific exit codes
if check_file "data.txt"; then
    echo "File is accessible"
else
    local exit_code=$?
    case $exit_code in
        $EXIT_NOT_FOUND)
            log_error "Create the file first"
            ;;
        $EXIT_PERMISSION_DENIED)
            log_error "Check file permissions"
            ;;
    esac
    exit $exit_code
fi
```

### Defensive Programming

```bash
# Check command success
if command_that_might_fail; then
    log_info "Command succeeded"
else
    log_error "Command failed with exit code: $?"
    return 1
fi

# Alternative with ||
command_that_might_fail || {
    log_error "Command failed"
    return 1
}

# Short-circuit evaluation
mkdir -p "$dir" || { log_error "Cannot create directory"; exit 1; }

# Validate before using
function safe_divide() {
    local numerator=$1
    local denominator=$2
    
    # Validate input (DFF)
    if [[ $denominator -eq 0 ]]; then
        log_error "Division by zero"
        return 1
    fi
    
    echo $((numerator / denominator))
    return 0
}

# Check return values
if result=$(dangerous_operation 2>&1); then
    log_info "Success: $result"
else
    log_error "Failed: $result"
    exit 1
fi
```

## Documentation Standards

### Header Documentation

Every script must have a comprehensive header:

```bash
#!/bin/bash
#
# File: deploy.sh
# Description: Deploy application to specified environment with rollback capability
# Version: 2.1.0
# Author: DevOps Team <devops@example.com>
# Created: 2024-01-15
# Last Modified: 2025-11-14
#
# Purpose:
#   Automates deployment of the application to staging or production environments.
#   Supports blue-green deployment, automatic rollback on failure, and health checks.
#   Implements zero-downtime deployment strategy.
#
# Usage: ./deploy.sh [OPTIONS] ENVIRONMENT
#   
#   ENVIRONMENT:
#     staging       Deploy to staging environment
#     production    Deploy to production (requires approval)
#
#   OPTIONS:
#     -h, --help              Display this help message
#     -v, --verbose           Enable verbose logging
#     -d, --dry-run           Preview deployment without applying
#     --skip-tests            Skip pre-deployment tests (not recommended)
#     --force                 Force deployment even with warnings
#     --rollback VERSION      Rollback to specified version
#
# Examples:
#   # Deploy to staging with verbose output
#   ./deploy.sh --verbose staging
#
#   # Dry run production deployment
#   ./deploy.sh --dry-run production
#
#   # Rollback production to previous version
#   ./deploy.sh --rollback v1.2.3 production
#
# Exit Codes:
#   0   Success
#   1   General error
#   2   Invalid arguments
#   3   Pre-deployment checks failed
#   4   Deployment failed
#   5   Health check failed
#   6   Rollback failed
#
# Dependencies:
#   - docker (20.10+)
#   - kubectl (1.25+)
#   - jq (1.6+)
#   - curl
#
# Environment Variables:
#   DEPLOY_TOKEN            Deployment authentication token (required)
#   SLACK_WEBHOOK_URL       Slack notification webhook (optional)
#   HEALTH_CHECK_ENDPOINT   Health check URL (default: /health)
#   DEPLOYMENT_TIMEOUT      Max deployment time in seconds (default: 600)
#
# Notes:
#   - Production deployments require manual confirmation unless --force is used
#   - All deployments are logged to logs/deployment-[timestamp].log
#   - Failed deployments automatically trigger rollback to previous version
#   - Supports blue-green deployment for zero downtime
#
# See Also:
#   - scripts/rollback.sh    - Manual rollback script
#   - scripts/health-check.sh - Standalone health check utility
#   - docs/deployment.md     - Comprehensive deployment documentation
#
```

### Function Documentation

```bash
#######################################
# Process payment transaction with comprehensive validation and error handling
#
# This function handles the complete payment processing workflow including:
# - Input validation and sanitization
# - Payment gateway integration
# - Retry logic for transient failures
# - Transaction logging and auditing
# - Error handling and rollback
#
# Implements DFF (Design for Failure) principle with multi-layer error handling
# and automatic retry for transient failures.
#
# Globals:
#   PAYMENT_GATEWAY_URL - Payment gateway API endpoint
#   PAYMENT_TIMEOUT     - Maximum time for payment processing (seconds)
#   MAX_RETRIES         - Maximum number of retry attempts
#
# Arguments:
#   $1 - Transaction ID (required, alphanumeric, 8-32 chars)
#   $2 - Amount in cents (required, positive integer)
#   $3 - Payment method (required, one of: credit_card|debit_card|paypal)
#   $4 - Customer ID (required, UUID format)
#
# Outputs:
#   Writes transaction result JSON to stdout
#   Logs all operations to LOG_FILE
#   Writes audit trail to audit.log
#
# Returns:
#   0 - Payment processed successfully
#   1 - Validation error (invalid input)
#   2 - Payment gateway error (after retries)
#   3 - Insufficient funds
#   4 - Payment method declined
#   5 - Fraud detected
#
# Example:
#   # Successful payment
#   result=$(process_payment "TXN123" "5000" "credit_card" "uuid-here")
#   echo "$result" | jq '.status'  # "success"
#
#   # Handle errors
#   if ! result=$(process_payment "$txn_id" "$amount" "$method" "$customer_id"); then
#       log_error "Payment failed: $result"
#       refund_customer "$customer_id" "$amount"
#   fi
#
# Notes:
#   - Amount must be in cents (e.g., 5000 = $50.00)
#   - Implements PCI DSS compliant logging (no sensitive data)
#   - Automatic retry for gateway timeouts and 5xx errors
#   - Fraud detection integrated via risk scoring API
#
# See Also:
#   refund_payment() - Refund processing function
#   validate_payment_method() - Payment method validation
#
#######################################
function process_payment() {
    local transaction_id="$1"
    local amount="$2"
    local payment_method="$3"
    local customer_id="$4"
    
    log_info "Processing payment: txn=$transaction_id, amount=$amount, method=$payment_method"
    
    # Validation (DFF: fail fast)
    validate_transaction_input "$transaction_id" "$amount" "$payment_method" "$customer_id" || {
        log_error "Payment validation failed"
        return 1
    }
    
    # Process with retry logic (DFF: handle transient failures)
    local result
    result=$(retry_command call_payment_gateway "$transaction_id" "$amount" "$payment_method") || {
        log_error "Payment processing failed after retries"
        return 2
    }
    
    # Audit logging
    log_payment_audit "$transaction_id" "$result"
    
    # Return result
    echo "$result"
    return 0
}
```

### Inline Comments

```bash
# Good comments explain WHY, not WHAT

# Good: Explains reasoning
# Use exponential backoff to handle API rate limits gracefully
# Starts at 1s, doubles each retry: 1s, 2s, 4s, 8s
for attempt in {1..4}; do
    sleep $((2 ** (attempt - 1)))
    api_call && break
done

# Bad: States the obvious
# Loop from 1 to 4
for attempt in {1..4}; do
    # Sleep
    sleep $((2 ** (attempt - 1)))
    # Call API and break if success
    api_call && break
done

# Good: Explains non-obvious behavior
# Set IFS to newline only to preserve spaces in filenames
# Default IFS includes space, tab, newline which breaks on spaces
while IFS= read -r filename; do
    echo "$filename"
done < file_list.txt

# Good: Documents workarounds
# Workaround for macOS sed requiring empty string after -i
# GNU sed doesn't need this, but it works on both
sed -i'' 's/old/new/g' file.txt

# Good: Explains business logic
# Apply discount tiers based on customer loyalty:
# - New customers: 5%
# - 1 year: 10%
# - 3+ years: 15%
local discount=5
[[ $years_member -ge 3 ]] && discount=15
[[ $years_member -ge 1 && $years_member -lt 3 ]] && discount=10
```

## Best Practices

### Safe Scripting Checklist

```bash
# At the top of every script:
#!/bin/bash
set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Use readonly for constants
readonly MAX_SIZE=1000
readonly API_URL="https://api.example.com"

# Use local for function variables
function my_function() {
    local temp_var="value"  # Function scoped
    # NOT: temp_var="value"  # Would be global
}

# Quote all variable expansions
echo "$variable"           # Correct
echo "${array[@]}"         # Correct
command "$file_path"       # Correct

# Check command existence before using
if ! command -v jq &> /dev/null; then
    log_error "jq is required but not installed"
    exit 1
fi

# Use $() instead of backticks
result=$(command arg)      # Preferred
result=`command arg`       # Avoid (legacy)

# Prefer [[ ]] over [ ] for tests
if [[ "$var" == "value" ]]; then  # Preferred
if [ "$var" = "value" ]; then     # Works but less features

# Use meaningful variable names
user_count=10              # Clear
uc=10                      # Unclear

# Validate inputs
function process() {
    local input="$1"
    
    # Validate before processing (DFF)
    if [[ -z "$input" ]]; then
        log_error "Input is required"
        return 1
    fi
    
    # Process
}

# Handle errors explicitly
if ! command_that_might_fail; then
    log_error "Command failed"
    exit 1
fi

# Clean up resources
trap cleanup EXIT          # Always cleanup
trap cleanup_on_error ERR  # Cleanup on error
```

### Common Patterns

#### Configuration Loading

```bash
#######################################
# Load configuration from file
# Supports .env format with KEY=VALUE pairs
# Arguments:
#   $1 - Config file path
# Returns:
#   0 on success, 1 if file not found or invalid
#######################################
function load_config() {
    local config_file="$1"
    
    if [[ ! -f "$config_file" ]]; then
        log_error "Config file not found: $config_file"
        return 1
    fi
    
    log_info "Loading configuration from: $config_file"
    
    # Load config, ignoring comments and empty lines
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
        
        # Remove quotes from value
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        
        # Export as environment variable
        export "$key=$value"
        log_debug "Loaded config: $key=$value"
    done < "$config_file"
    
    return 0
}
```

#### File Processing

```bash
#######################################
# Process file line by line safely
# Arguments:
#   $1 - Input file path
# Returns:
#   0 on success, 1 on error
#######################################
function process_file_line_by_line() {
    local input_file="$1"
    local line_number=0
    
    # Validate file exists
    [[ ! -f "$input_file" ]] && return 1
    
    # Process line by line (preserves spaces and special chars)
    while IFS= read -r line || [[ -n "$line" ]]; do
        ((line_number++))
        
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^#.*$ ]] && continue
        
        # Process line
        log_debug "Processing line $line_number: $line"
        
        # Your processing logic here
        echo "$line" | process_line
        
    done < "$input_file"
    
    log_info "Processed $line_number lines from $input_file"
    return 0
}
```

#### Parallel Processing

```bash
#######################################
# Process items in parallel with job control
# Arguments:
#   $@ - Items to process
# Globals:
#   MAX_PARALLEL_JOBS
# Returns:
#   0 if all jobs succeed, 1 if any fail
#######################################
function process_parallel() {
    local items=("$@")
    local max_jobs="${MAX_PARALLEL_JOBS:-4}"
    local failed_jobs=0
    
    log_info "Processing ${#items[@]} items with $max_jobs parallel jobs"
    
    # Process items in parallel
    for item in "${items[@]}"; do
        # Wait if too many background jobs
        while [[ $(jobs -r | wc -l) -ge $max_jobs ]]; do
            sleep 0.1
        done
        
        # Start job in background
        (
            log_info "Processing: $item"
            process_single_item "$item" || exit 1
        ) &
    done
    
    # Wait for all background jobs
    for job in $(jobs -p); do
        if ! wait "$job"; then
            ((failed_jobs++))
            log_error "Job failed: $job"
        fi
    done
    
    if [[ $failed_jobs -gt 0 ]]; then
        log_error "Failed jobs: $failed_jobs"
        return 1
    fi
    
    log_info "All jobs completed successfully"
    return 0
}
```

#### HTTP API Calls

```bash
#######################################
# Make HTTP API call with retry and error handling
# Arguments:
#   $1 - HTTP method (GET|POST|PUT|DELETE)
#   $2 - API endpoint URL
#   $3 - Request body (optional, for POST/PUT)
# Returns:
#   0 on success, 1 on failure
# Outputs:
#   API response body to stdout
#######################################
function api_call() {
    local method="$1"
    local url="$2"
    local body="${3:-}"
    
    local curl_args=(
        --silent
        --show-error
        --fail
        --max-time "$TIMEOUT"
        --retry 3
        --retry-delay 2
        --header "Authorization: Bearer ${API_KEY}"
        --header "Content-Type: application/json"
    )
    
    # Add method and body for POST/PUT
    case "$method" in
        POST|PUT)
            [[ -z "$body" ]] && { log_error "Body required for $method"; return 1; }
            curl_args+=(
                --request "$method"
                --data "$body"
            )
            ;;
        GET|DELETE)
            curl_args+=(--request "$method")
            ;;
        *)
            log_error "Unsupported HTTP method: $method"
            return 1
            ;;
    esac
    
    log_debug "API call: $method $url"
    
    # Make API call with error handling
    local response
    local http_code
    local temp_file
    temp_file=$(mktemp)
    
    # Capture both response and HTTP status code
    http_code=$(curl "${curl_args[@]}" \
        --write-out "%{http_code}" \
        --output "$temp_file" \
        "$url")
    
    local curl_exit=$?
    response=$(<"$temp_file")
    rm -f "$temp_file"
    
    # Check for curl errors
    if [[ $curl_exit -ne 0 ]]; then
        log_error "Curl failed with exit code: $curl_exit"
        return 1
    fi
    
    # Check HTTP status code
    if [[ "$http_code" -ge 400 ]]; then
        log_error "API returned error: HTTP $http_code"
        log_error "Response: $response"
        return 1
    fi
    
    # Output response
    echo "$response"
    return 0
}
```

#### Lock Files (Prevent Concurrent Execution)

```bash
#######################################
# Acquire exclusive lock to prevent concurrent execution
# Globals:
#   LOCK_FILE
# Returns:
#   0 if lock acquired, 1 if already locked
#######################################
function acquire_lock() {
    readonly LOCK_FILE="/tmp/${SCRIPT_NAME}.lock"
    
    # Check if another instance is running
    if [[ -f "$LOCK_FILE" ]]; then
        local lock_pid
        lock_pid=$(<"$LOCK_FILE")
        
        # Check if process is still running
        if kill -0 "$lock_pid" 2>/dev/null; then
            log_error "Another instance is already running (PID: $lock_pid)"
            return 1
        else
            log_warn "Stale lock file found, removing"
            rm -f "$LOCK_FILE"
        fi
    fi
    
    # Create lock file with current PID
    echo "$$" > "$LOCK_FILE" || {
        log_error "Failed to create lock file"
        return 1
    }
    
    log_debug "Lock acquired: $LOCK_FILE"
    return 0
}

#######################################
# Release lock file
# Globals:
#   LOCK_FILE
#######################################
function release_lock() {
    if [[ -f "${LOCK_FILE:-}" ]]; then
        rm -f "$LOCK_FILE"
        log_debug "Lock released: $LOCK_FILE"
    fi
}

# Add to cleanup
trap 'release_lock; cleanup' EXIT
```

## Advanced Patterns

### JSON Processing

```bash
# Parse JSON with jq
function parse_json_response() {
    local json="$1"
    
    # Extract fields
    local status
    status=$(echo "$json" | jq -r '.status')
    
    local message
    message=$(echo "$json" | jq -r '.message')
    
    local items
    items=$(echo "$json" | jq -r '.items[]')
    
    # Check for null
    if [[ "$status" == "null" ]]; then
        log_error "Invalid JSON response"
        return 1
    fi
    
    echo "Status: $status"
    echo "Message: $message"
    echo "Items: $items"
}

# Build JSON
function build_json_request() {
    local name="$1"
    local value="$2"
    
    # Use jq to build JSON safely (handles escaping)
    jq -n \
        --arg name "$name" \
        --arg value "$value" \
        '{name: $name, value: $value, timestamp: now}'
}
```

### Date and Time Handling

```bash
# Current timestamp
readonly TIMESTAMP=$(date +%Y%m%d-%H%M%S)
readonly ISO_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Date arithmetic
local tomorrow
tomorrow=$(date -d "tomorrow" +%Y-%m-%d)  # GNU date

local tomorrow_macos
tomorrow_macos=$(date -v+1d +%Y-%m-%d)  # macOS date

# Portable date function
function add_days() {
    local days=$1
    
    if date --version &>/dev/null; then
        # GNU date (Linux)
        date -d "+${days} days" +%Y-%m-%d
    else
        # BSD date (macOS)
        date -v+${days}d +%Y-%m-%d
    fi
}

# Measure execution time
function measure_time() {
    local start_time
    start_time=$(date +%s)
    
    # Execute command
    "$@"
    
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log_info "Execution time: ${duration}s"
    return 0
}
```

### Progress Tracking

```bash
# Progress for known item count
function process_with_progress() {
    local items=("$@")
    local total=${#items[@]}
    local current=0
    
    for item in "${items[@]}"; do
        ((current++))
        local progress=$((current * 100 / total))
        
        show_progress "$progress" "Processing items"
        
        process_single_item "$item"
    done
    
    echo ""  # New line after progress
}
```

## Testing Bash Scripts

### Unit Testing with bats

```bash
# test_script.bats
#!/usr/bin/env bats

# Setup function runs before each test
setup() {
    # Source script to test
    source "${BATS_TEST_DIRNAME}/../script.sh"
    
    # Create temporary directory
    TEST_TEMP_DIR="$(mktemp -d)"
}

# Teardown function runs after each test
teardown() {
    # Clean up
    [[ -d "$TEST_TEMP_DIR" ]] && rm -rf "$TEST_TEMP_DIR"
}

@test "validate_email: accepts valid email" {
    run validate_email "user@example.com"
    [ "$status" -eq 0 ]
}

@test "validate_email: rejects invalid email" {
    run validate_email "invalid-email"
    [ "$status" -eq 1 ]
}

@test "process_file: handles missing file" {
    run process_file "/nonexistent/file.txt"
    [ "$status" -eq 4 ]  # EXIT_NOT_FOUND
    [[ "$output" =~ "File not found" ]]
}

@test "retry_command: succeeds on second attempt" {
    # Mock function that fails once then succeeds
    function flaky_command() {
        [[ -f "/tmp/first_attempt" ]] && return 0
        touch "/tmp/first_attempt"
        return 1
    }
    
    run retry_command flaky_command
    [ "$status" -eq 0 ]
    
    rm -f "/tmp/first_attempt"
}
```

### Integration Testing

```bash
# test_integration.sh
#!/bin/bash
set -euo pipefail

# Test full script execution
function test_successful_execution() {
    echo "Test: Successful execution"
    
    # Run script with test input
    if ./script.sh --dry-run test-input.txt; then
        echo "✅ PASS: Script executed successfully"
    else
        echo "❌ FAIL: Script failed"
        return 1
    fi
}

function test_handles_missing_file() {
    echo "Test: Handle missing file"
    
    # Expect failure
    if ./script.sh nonexistent.txt 2>/dev/null; then
        echo "❌ FAIL: Should have failed with missing file"
        return 1
    else
        echo "✅ PASS: Correctly handled missing file"
    fi
}

# Run all tests
function run_tests() {
    local failed=0
    
    test_successful_execution || ((failed++))
    test_handles_missing_file || ((failed++))
    
    echo ""
    if [[ $failed -eq 0 ]]; then
        echo "✅ All tests passed"
        return 0
    else
        echo "❌ $failed test(s) failed"
        return 1
    fi
}

run_tests
```

## Security Best Practices

### Secrets Management

```bash
# Never hardcode secrets
readonly API_KEY="abc123"  # ❌ NEVER DO THIS

# Use environment variables
readonly API_KEY="${API_KEY}"  # ✅ From environment

# Validate secrets are set
if [[ -z "${API_KEY:-}" ]]; then
    log_error "API_KEY environment variable is required"
    exit 3
fi

# Load from secure file (restrict permissions)
if [[ -f "$HOME/.secrets" ]]; then
    # Check permissions (should be 600)
    local perms
    perms=$(stat -c %a "$HOME/.secrets" 2>/dev/null || stat -f %A "$HOME/.secrets")
    
    if [[ "$perms" != "600" ]]; then
        log_error "Insecure permissions on secrets file: $perms"
        log_error "Fix with: chmod 600 $HOME/.secrets"
        exit 5
    fi
    
    source "$HOME/.secrets"
fi

# Don't log secrets
log_info "API call to ${API_ENDPOINT}"  # ✅ Don't log API_KEY
# NOT: log_info "API call with key: $API_KEY"  # ❌ Logs secret
```

### Input Sanitization

```bash
# Sanitize user input to prevent injection
function sanitize_input() {
    local input="$1"
    
    # Remove dangerous characters
    input="${input//[^a-zA-Z0-9._-]/}"
    
    # Limit length
    input="${input:0:255}"
    
    echo "$input"
}

# Validate input format
function validate_filename() {
    local filename="$1"
    
    # Check for path traversal attempts
    if [[ "$filename" =~ \.\. ]]; then
        log_error "Path traversal detected in filename"
        return 1
    fi
    
    # Check for absolute paths (if not allowed)
    if [[ "$filename" =~ ^/ ]]; then
        log_error "Absolute paths not allowed"
        return 1
    fi
    
    # Valid
    return 0
}

# Use -- to separate options from arguments
rm -- "$user_provided_filename"  # Prevents -rf from being interpreted as option
```

## Performance Optimization

### Efficient Patterns

```bash
# Avoid unnecessary subshells
# Slow: Creates subshell for each iteration
for file in $(ls *.txt); do
    echo "$file"
done

# Fast: Direct glob expansion
for file in *.txt; do
    [[ -f "$file" ]] && echo "$file"
done

# Avoid repeated command calls
# Slow: Calls date multiple times
for i in {1..100}; do
    echo "$(date): Item $i"
done

# Fast: Call date once
current_date=$(date)
for i in {1..100}; do
    echo "$current_date: Item $i"
done

# Use built-in string operations instead of external commands
# Slow: Uses sed
filename=$(echo "$path" | sed 's/.*\///')

# Fast: Built-in parameter expansion
filename="${path##*/}"

# Built-in string operations
str="Hello World"
echo "${str,,}"        # Lowercase: hello world
echo "${str^^}"        # Uppercase: HELLO WORLD
echo "${str:0:5}"      # Substring: Hello
echo "${str/World/Bash}"  # Replace: Hello Bash

# Remove prefix/suffix
path="/path/to/file.txt"
echo "${path##*/}"     # Filename: file.txt
echo "${path%.*}"      # Remove extension: /path/to/file
echo "${path##*.}"     # Extension: txt
```

---

**Version:** 1.0.0 | **Last Modified:** 2025-11-14 | **Author:** Amr Abdel-Motaleb

**Purpose:** Comprehensive bash scripting standards for robust, maintainable, production-ready scripts across all project types. Embodies DFF (comprehensive error handling), DRY (reusable functions), and KIS (clear, simple logic) principles.

