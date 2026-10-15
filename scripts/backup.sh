#!/bin/bash
# =============================================================================
# Smart Home SQLite Backup Script
# =============================================================================
# Backs up all SQLite databases from the smart-home services.
# Uses sqlite3 .backup for safe hot backups (no locking issues).
# Rotates backups keeping the last 7 days.
#
# Usage: ./backup.sh [--dry-run]
# =============================================================================

set -euo pipefail

# Configuration
readonly PROD_DIR="${HOME}/smart-home-prod"
readonly DATA_DIR="${PROD_DIR}/data"
readonly BACKUP_ROOT="${HOME}/backups/smart-home"
readonly DATE_STAMP=$(date +%Y-%m-%d)
readonly BACKUP_DIR="${BACKUP_ROOT}/${DATE_STAMP}"
readonly LOG_FILE="${BACKUP_ROOT}/backup.log"
readonly RETENTION_DAYS=7

# Databases to backup (relative to DATA_DIR)
declare -A DATABASES=(
    ["auth"]="dashboard/auth.db"
    ["casita"]="casita-suenos/casita.db"
    ["portfolio"]="portfolio-monitor/portfolio.db"
    ["baby-gifts"]="baby-gifts-service/baby-gifts.db"
    ["metrics"]="metrics-service/metrics.db"
    ["energy"]="energy-monitor/energy.db"
    ["presence"]="presence-service/presence.db"
    ["calendar"]="calendar-service/calendar.db"
)

# Vaultwarden backup (separate path)
readonly VAULTWARDEN_DATA="${PROD_DIR}/vaultwarden-data"

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

# Dry run mode
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

# -----------------------------------------------------------------------------
# Logging functions
# -----------------------------------------------------------------------------
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Console output with colors
    case "$level" in
        INFO)  echo -e "${GREEN}[INFO]${NC} $message" ;;
        WARN)  echo -e "${YELLOW}[WARN]${NC} $message" ;;
        ERROR) echo -e "${RED}[ERROR]${NC} $message" ;;
    esac
    
    # Log file output (no colors)
    if [[ "$DRY_RUN" == false ]]; then
        echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
    fi
}

log_info()  { log INFO "$@"; }
log_warn()  { log WARN "$@"; }
log_error() { log ERROR "$@"; }

# -----------------------------------------------------------------------------
# Check prerequisites
# -----------------------------------------------------------------------------
check_prerequisites() {
    if ! command -v sqlite3 &> /dev/null; then
        log_error "sqlite3 is not installed. Please install it first."
        exit 1
    fi
    
    # Check disk space (require at least 500MB free)
    local free_space
    free_space=$(df -m "${BACKUP_ROOT%/*}" 2>/dev/null | awk 'NR==2 {print $4}' || echo "0")
    if [[ "$free_space" -lt 500 ]]; then
        log_error "Insufficient disk space. Only ${free_space}MB available, need at least 500MB."
        exit 1
    fi
}

# -----------------------------------------------------------------------------
# Create backup directory
# -----------------------------------------------------------------------------
create_backup_dir() {
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would create directory: $BACKUP_DIR"
        return 0
    fi
    
    mkdir -p "$BACKUP_DIR"
    mkdir -p "$(dirname "$LOG_FILE")"
    log_info "Created backup directory: $BACKUP_DIR"
}

# -----------------------------------------------------------------------------
# Backup a single SQLite database
# -----------------------------------------------------------------------------
backup_database() {
    local name="$1"
    local source_path="$2"
    local full_source="${DATA_DIR}/${source_path}"
    local backup_path="${BACKUP_DIR}/${name}.db"
    
    # Check if source exists
    if [[ ! -f "$full_source" ]]; then
        log_warn "Database not found (skipping): $full_source"
        return 0
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        local size
        size=$(du -h "$full_source" 2>/dev/null | cut -f1 || echo "?")
        log_info "[DRY-RUN] Would backup: $name ($size) -> $backup_path"
        return 0
    fi
    
    # Perform the backup using sqlite3 .backup command
    # This is safe for hot backups - it handles WAL mode correctly
    log_info "Backing up: $name"
    
    if sqlite3 "$full_source" ".backup '$backup_path'" 2>/dev/null; then
        local size
        size=$(du -h "$backup_path" | cut -f1)
        log_info "  -> Success: $backup_path ($size)"
        return 0
    else
        # If .backup fails, the database might be locked or corrupted
        # Try a simple copy as fallback (less safe but better than nothing)
        log_warn "  -> sqlite3 .backup failed, trying copy fallback"
        if cp "$full_source" "$backup_path" 2>/dev/null; then
            local size
            size=$(du -h "$backup_path" | cut -f1)
            log_warn "  -> Fallback copy succeeded: $backup_path ($size)"
            return 0
        else
            log_error "  -> Failed to backup: $name"
            return 1
        fi
    fi
}

# -----------------------------------------------------------------------------
# Backup Vaultwarden data
# -----------------------------------------------------------------------------
backup_vaultwarden() {
    local vw_db="${VAULTWARDEN_DATA}/db.sqlite3"
    local backup_path="${BACKUP_DIR}/vaultwarden.db"
    
    if [[ ! -f "$vw_db" ]]; then
        log_warn "Vaultwarden database not found (skipping): $vw_db"
        return 0
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        local size
        size=$(du -h "$vw_db" 2>/dev/null | cut -f1 || echo "?")
        log_info "[DRY-RUN] Would backup: vaultwarden ($size) -> $backup_path"
        return 0
    fi
    
    log_info "Backing up: vaultwarden"
    
    if sqlite3 "$vw_db" ".backup '$backup_path'" 2>/dev/null; then
        local size
        size=$(du -h "$backup_path" | cut -f1)
        log_info "  -> Success: $backup_path ($size)"
        
        # Also backup attachments if they exist
        local attachments_dir="${VAULTWARDEN_DATA}/attachments"
        if [[ -d "$attachments_dir" ]]; then
            local attachments_backup="${BACKUP_DIR}/vaultwarden-attachments"
            cp -r "$attachments_dir" "$attachments_backup" 2>/dev/null || true
            log_info "  -> Attachments backed up"
        fi
        return 0
    else
        log_warn "  -> sqlite3 .backup failed, trying copy fallback"
        if cp "$vw_db" "$backup_path" 2>/dev/null; then
            log_warn "  -> Fallback copy succeeded"
            return 0
        else
            log_error "  -> Failed to backup: vaultwarden"
            return 1
        fi
    fi
}

# -----------------------------------------------------------------------------
# Rotate old backups (keep last N days)
# -----------------------------------------------------------------------------
rotate_backups() {
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would rotate backups older than ${RETENTION_DAYS} days"
        # Show what would be deleted
        if [[ -d "$BACKUP_ROOT" ]]; then
            local old_dirs
            old_dirs=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" -mtime +${RETENTION_DAYS} 2>/dev/null || true)
            if [[ -n "$old_dirs" ]]; then
                echo "$old_dirs" | while read -r dir; do
                    log_info "[DRY-RUN] Would delete: $dir"
                done
            fi
        fi
        return 0
    fi
    
    log_info "Rotating backups older than ${RETENTION_DAYS} days..."
    
    if [[ -d "$BACKUP_ROOT" ]]; then
        local deleted=0
        while IFS= read -r dir; do
            if [[ -n "$dir" && -d "$dir" ]]; then
                rm -r "$dir"
                log_info "  -> Deleted: $dir"
                ((deleted++)) || true
            fi
        done < <(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" -mtime +${RETENTION_DAYS} 2>/dev/null)
        
        if [[ $deleted -eq 0 ]]; then
            log_info "  -> No old backups to delete"
        else
            log_info "  -> Deleted $deleted old backup(s)"
        fi
    fi
}

# -----------------------------------------------------------------------------
# Generate backup summary
# -----------------------------------------------------------------------------
generate_summary() {
    if [[ "$DRY_RUN" == true ]]; then
        return 0
    fi
    
    local summary_file="${BACKUP_DIR}/BACKUP_SUMMARY.txt"
    {
        echo "Smart Home Backup Summary"
        echo "========================="
        echo "Date: $(date)"
        echo "Backup Directory: $BACKUP_DIR"
        echo ""
        echo "Files:"
        ls -lh "$BACKUP_DIR" 2>/dev/null || echo "  (none)"
        echo ""
        echo "Total Size:"
        du -sh "$BACKUP_DIR" 2>/dev/null || echo "  (unknown)"
    } > "$summary_file"
    
    log_info "Summary written to: $summary_file"
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    local start_time
    start_time=$(date +%s)
    local errors=0
    
    echo "=============================================="
    echo "Smart Home Backup - ${DATE_STAMP}"
    echo "=============================================="
    
    if [[ "$DRY_RUN" == true ]]; then
        echo "(Running in DRY-RUN mode - no changes will be made)"
        echo ""
    fi
    
    # Pre-flight checks
    check_prerequisites
    create_backup_dir
    
    # Backup all databases
    log_info "Starting database backups..."
    for name in "${!DATABASES[@]}"; do
        if ! backup_database "$name" "${DATABASES[$name]}"; then
            ((errors++)) || true
        fi
    done
    
    # Backup Vaultwarden
    if ! backup_vaultwarden; then
        ((errors++)) || true
    fi
    
    # Rotate old backups
    rotate_backups
    
    # Generate summary
    generate_summary
    
    # Final report
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    echo ""
    echo "=============================================="
    if [[ $errors -eq 0 ]]; then
        log_info "Backup completed successfully in ${duration}s"
    else
        log_warn "Backup completed with ${errors} error(s) in ${duration}s"
    fi
    echo "=============================================="
    
    exit $errors
}

main "$@"
