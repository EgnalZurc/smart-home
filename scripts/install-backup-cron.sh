#!/bin/bash
# =============================================================================
# Install Backup Cron Job
# =============================================================================
# Installs a daily cron job to run the smart-home backup script at 3:00 AM.
# This script is idempotent - running it multiple times will not create
# duplicate cron entries.
#
# Usage: ./install-backup-cron.sh [--uninstall]
# =============================================================================

set -euo pipefail

# Configuration
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly BACKUP_SCRIPT="${SCRIPT_DIR}/backup.sh"
readonly CRON_SCHEDULE="0 3 * * *"  # Daily at 3:00 AM
readonly CRON_MARKER="# smart-home-backup"

# Colors
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# -----------------------------------------------------------------------------
# Check if backup script exists and is executable
# -----------------------------------------------------------------------------
check_backup_script() {
    if [[ ! -f "$BACKUP_SCRIPT" ]]; then
        log_error "Backup script not found: $BACKUP_SCRIPT"
        exit 1
    fi
    
    if [[ ! -x "$BACKUP_SCRIPT" ]]; then
        log_warn "Making backup script executable..."
        chmod +x "$BACKUP_SCRIPT"
    fi
    
    log_info "Backup script verified: $BACKUP_SCRIPT"
}

# -----------------------------------------------------------------------------
# Check if cron job already exists
# -----------------------------------------------------------------------------
cron_exists() {
    crontab -l 2>/dev/null | grep -q "$CRON_MARKER"
}

# -----------------------------------------------------------------------------
# Install the cron job
# -----------------------------------------------------------------------------
install_cron() {
    if cron_exists; then
        log_warn "Cron job already installed. Use --uninstall to remove it first."
        show_current_cron
        return 0
    fi
    
    # Build the cron entry
    local cron_entry="${CRON_SCHEDULE} ${BACKUP_SCRIPT} >> ${HOME}/backups/smart-home/cron.log 2>&1 ${CRON_MARKER}"
    
    # Get existing crontab and append new entry
    (crontab -l 2>/dev/null || true; echo "$cron_entry") | crontab -
    
    log_info "Cron job installed successfully!"
    log_info "Schedule: Daily at 3:00 AM"
    log_info "Command: $BACKUP_SCRIPT"
    log_info "Log: ${HOME}/backups/smart-home/cron.log"
    
    echo ""
    show_current_cron
}

# -----------------------------------------------------------------------------
# Uninstall the cron job
# -----------------------------------------------------------------------------
uninstall_cron() {
    if ! cron_exists; then
        log_warn "No cron job found to uninstall."
        return 0
    fi
    
    # Remove the cron entry
    crontab -l 2>/dev/null | grep -v "$CRON_MARKER" | crontab -
    
    log_info "Cron job uninstalled successfully!"
}

# -----------------------------------------------------------------------------
# Show current cron configuration
# -----------------------------------------------------------------------------
show_current_cron() {
    log_info "Current crontab entries for smart-home backup:"
    crontab -l 2>/dev/null | grep "$CRON_MARKER" || echo "  (none)"
}

# -----------------------------------------------------------------------------
# Verify cron daemon is running
# -----------------------------------------------------------------------------
verify_cron_daemon() {
    if command -v systemctl &> /dev/null; then
        if systemctl is-active --quiet cron 2>/dev/null || systemctl is-active --quiet crond 2>/dev/null; then
            log_info "Cron daemon is running"
            return 0
        fi
    fi
    
    # Fallback: check process
    if pgrep -x "cron" > /dev/null 2>&1 || pgrep -x "crond" > /dev/null 2>&1; then
        log_info "Cron daemon is running"
        return 0
    fi
    
    log_warn "Could not verify cron daemon is running. Make sure cron/crond service is enabled."
}

# -----------------------------------------------------------------------------
# Usage
# -----------------------------------------------------------------------------
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Install or manage the smart-home backup cron job."
    echo ""
    echo "Options:"
    echo "  --uninstall   Remove the cron job"
    echo "  --status      Show current cron job status"
    echo "  --test        Run backup script once (dry-run)"
    echo "  -h, --help    Show this help message"
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    case "${1:-}" in
        --uninstall)
            uninstall_cron
            ;;
        --status)
            verify_cron_daemon
            show_current_cron
            ;;
        --test)
            check_backup_script
            log_info "Running backup script in dry-run mode..."
            "$BACKUP_SCRIPT" --dry-run
            ;;
        -h|--help)
            usage
            ;;
        "")
            check_backup_script
            verify_cron_daemon
            install_cron
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
}

main "$@"
