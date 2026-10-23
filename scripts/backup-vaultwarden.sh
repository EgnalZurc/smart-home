#!/bin/bash
# =============================================================================
# Vaultwarden Dedicated Backup Script
# =============================================================================
# Creates complete backups of Vaultwarden data:
# - SQLite database (using sqlite3 .backup for hot/online backup)
# - RSA key files (critical for decryption)
# - Attachments directory
#
# Keeps the last 7 daily backups with automatic rotation.
#
# SETUP INSTRUCTIONS:
# -------------------
# 1. Copy this script to the Pi:
#    scp scripts/backup-vaultwarden.sh pi@raspberrypi.local:~/projects/smart-home/scripts/
#
# 2. Make it executable:
#    ssh pi@raspberrypi.local "chmod +x ~/projects/smart-home/scripts/backup-vaultwarden.sh"
#
# 3. Verify paths match your deployment:
#    - VAULTWARDEN_DATA should point to your vaultwarden data directory
#    - Default: ~/smart-home-prod/data/vaultwarden
#
# 4. Test with dry-run:
#    ssh pi@raspberrypi.local "~/projects/smart-home/scripts/backup-vaultwarden.sh --dry-run"
#
# 5. Add to crontab for daily backups at 3 AM:
#    ssh pi@raspberrypi.local "crontab -e"
#    Add: 0 3 * * * /home/pi/projects/smart-home/scripts/backup-vaultwarden.sh >> /var/log/vaultwarden-backup.log 2>&1
#
# RESTORE INSTRUCTIONS:
# ---------------------
# 1. Stop vaultwarden container:
#    docker compose stop vaultwarden
#
# 2. Copy backup files to data directory:
#    cp /path/to/backup/YYYY-MM-DD/db.sqlite3 ~/smart-home-prod/data/vaultwarden/
#    cp /path/to/backup/YYYY-MM-DD/rsa_key.* ~/smart-home-prod/data/vaultwarden/
#
# 3. Restart vaultwarden:
#    docker compose up -d vaultwarden
#
# =============================================================================

set -euo pipefail

# Configuration - adjust paths if needed
readonly VAULTWARDEN_DATA="${HOME}/smart-home-prod/data/vaultwarden"
readonly BACKUP_ROOT="${HOME}/backups/vaultwarden"
readonly DATE_STAMP=$(date +%Y-%m-%d)
readonly BACKUP_DIR="${BACKUP_ROOT}/${DATE_STAMP}"
readonly LOG_FILE="/var/log/vaultwarden-backup.log"
readonly RETENTION_DAYS=7

# Files to backup
readonly DB_FILE="db.sqlite3"
readonly RSA_KEY_PEM="rsa_key.pem"
readonly RSA_KEY_DER="rsa_key.der"
readonly RSA_KEY_PUB="rsa_key.pub.der"

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
    
    # Console output
    echo "[$timestamp] [$level] $message"
    
    # Also write to log file (if writable and not dry-run)
    if [[ "$DRY_RUN" == false ]] && [[ -w "$(dirname "$LOG_FILE")" || -w "$LOG_FILE" ]]; then
        echo "[$timestamp] [$level] $message" >> "$LOG_FILE" 2>/dev/null || true
    fi
}

log_info()  { log INFO "$@"; }
log_warn()  { log WARN "$@"; }
log_error() { log ERROR "$@"; }

# -----------------------------------------------------------------------------
# Check prerequisites
# -----------------------------------------------------------------------------
check_prerequisites() {
    # Check sqlite3 is available
    if ! command -v sqlite3 &> /dev/null; then
        log_error "sqlite3 is not installed. Install with: sudo apt-get install sqlite3"
        exit 1
    fi
    
    # Check vaultwarden data directory exists
    if [[ ! -d "$VAULTWARDEN_DATA" ]]; then
        log_error "Vaultwarden data directory not found: $VAULTWARDEN_DATA"
        log_error "Please verify the VAULTWARDEN_DATA path in this script."
        exit 1
    fi
    
    # Check database exists
    if [[ ! -f "${VAULTWARDEN_DATA}/${DB_FILE}" ]]; then
        log_error "Vaultwarden database not found: ${VAULTWARDEN_DATA}/${DB_FILE}"
        exit 1
    fi
    
    # Check RSA key exists (critical for decryption)
    if [[ ! -f "${VAULTWARDEN_DATA}/${RSA_KEY_PEM}" ]]; then
        log_warn "RSA key not found: ${VAULTWARDEN_DATA}/${RSA_KEY_PEM}"
        log_warn "This is unusual - Vaultwarden should create this on first run."
    fi
    
    # Check disk space (require at least 200MB free)
    local backup_parent
    backup_parent=$(dirname "$BACKUP_ROOT")
    mkdir -p "$backup_parent" 2>/dev/null || true
    
    local free_space
    free_space=$(df -m "$backup_parent" 2>/dev/null | awk 'NR==2 {print $4}' || echo "0")
    if [[ "$free_space" -lt 200 ]]; then
        log_error "Insufficient disk space. Only ${free_space}MB available, need at least 200MB."
        exit 1
    fi
    
    log_info "Prerequisites check passed"
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
    log_info "Created backup directory: $BACKUP_DIR"
}

# -----------------------------------------------------------------------------
# Backup SQLite database using .backup command (hot/online backup)
# -----------------------------------------------------------------------------
backup_database() {
    local source="${VAULTWARDEN_DATA}/${DB_FILE}"
    local dest="${BACKUP_DIR}/${DB_FILE}"
    
    if [[ "$DRY_RUN" == true ]]; then
        local size
        size=$(du -h "$source" 2>/dev/null | cut -f1 || echo "?")
        log_info "[DRY-RUN] Would backup database: $source ($size)"
        return 0
    fi
    
    log_info "Backing up database (online backup, no downtime)..."
    
    # sqlite3 .backup is safe for hot backups:
    # - It creates a consistent snapshot even while the database is in use
    # - It handles WAL mode correctly
    # - It doesn't require stopping the container
    if sqlite3 "$source" ".backup '${dest}'" 2>/dev/null; then
        local size
        size=$(du -h "$dest" | cut -f1)
        log_info "  -> Database backed up: $dest ($size)"
        
        # Verify backup integrity
        if sqlite3 "$dest" "PRAGMA integrity_check;" 2>/dev/null | grep -q "ok"; then
            log_info "  -> Integrity check passed"
        else
            log_warn "  -> Integrity check returned warnings (backup may still be usable)"
        fi
        return 0
    else
        log_error "  -> Failed to backup database with sqlite3 .backup"
        # Fallback to file copy (less safe but better than nothing)
        log_warn "  -> Attempting fallback file copy..."
        if cp "$source" "$dest" 2>/dev/null; then
            log_warn "  -> Fallback copy succeeded (may be inconsistent if DB was being written)"
            return 0
        else
            log_error "  -> Fallback copy also failed"
            return 1
        fi
    fi
}

# -----------------------------------------------------------------------------
# Backup RSA keys (critical for decryption)
# -----------------------------------------------------------------------------
backup_rsa_keys() {
    local keys_backed_up=0
    
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would backup RSA keys"
        return 0
    fi
    
    log_info "Backing up RSA keys..."
    
    # rsa_key.pem - main private key (most critical)
    if [[ -f "${VAULTWARDEN_DATA}/${RSA_KEY_PEM}" ]]; then
        cp "${VAULTWARDEN_DATA}/${RSA_KEY_PEM}" "${BACKUP_DIR}/${RSA_KEY_PEM}"
        log_info "  -> ${RSA_KEY_PEM} backed up"
        ((keys_backed_up++))
    fi
    
    # rsa_key.der - DER format private key
    if [[ -f "${VAULTWARDEN_DATA}/${RSA_KEY_DER}" ]]; then
        cp "${VAULTWARDEN_DATA}/${RSA_KEY_DER}" "${BACKUP_DIR}/${RSA_KEY_DER}"
        log_info "  -> ${RSA_KEY_DER} backed up"
        ((keys_backed_up++))
    fi
    
    # rsa_key.pub.der - public key
    if [[ -f "${VAULTWARDEN_DATA}/${RSA_KEY_PUB}" ]]; then
        cp "${VAULTWARDEN_DATA}/${RSA_KEY_PUB}" "${BACKUP_DIR}/${RSA_KEY_PUB}"
        log_info "  -> ${RSA_KEY_PUB} backed up"
        ((keys_backed_up++))
    fi
    
    if [[ $keys_backed_up -eq 0 ]]; then
        log_warn "  -> No RSA keys found to backup"
        return 1
    fi
    
    log_info "  -> $keys_backed_up RSA key file(s) backed up"
    return 0
}

# -----------------------------------------------------------------------------
# Backup attachments directory (if exists)
# -----------------------------------------------------------------------------
backup_attachments() {
    local attachments_dir="${VAULTWARDEN_DATA}/attachments"
    
    if [[ ! -d "$attachments_dir" ]]; then
        log_info "No attachments directory found (skipping)"
        return 0
    fi
    
    # Check if directory has any files
    if [[ -z "$(ls -A "$attachments_dir" 2>/dev/null)" ]]; then
        log_info "Attachments directory is empty (skipping)"
        return 0
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        local size
        size=$(du -sh "$attachments_dir" 2>/dev/null | cut -f1 || echo "?")
        log_info "[DRY-RUN] Would backup attachments directory ($size)"
        return 0
    fi
    
    log_info "Backing up attachments..."
    
    if cp -r "$attachments_dir" "${BACKUP_DIR}/attachments" 2>/dev/null; then
        local size
        size=$(du -sh "${BACKUP_DIR}/attachments" | cut -f1)
        log_info "  -> Attachments backed up ($size)"
        return 0
    else
        log_error "  -> Failed to backup attachments"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Backup sends directory (if exists)
# -----------------------------------------------------------------------------
backup_sends() {
    local sends_dir="${VAULTWARDEN_DATA}/sends"
    
    if [[ ! -d "$sends_dir" ]]; then
        log_info "No sends directory found (skipping)"
        return 0
    fi
    
    if [[ -z "$(ls -A "$sends_dir" 2>/dev/null)" ]]; then
        log_info "Sends directory is empty (skipping)"
        return 0
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        local size
        size=$(du -sh "$sends_dir" 2>/dev/null | cut -f1 || echo "?")
        log_info "[DRY-RUN] Would backup sends directory ($size)"
        return 0
    fi
    
    log_info "Backing up sends..."
    
    if cp -r "$sends_dir" "${BACKUP_DIR}/sends" 2>/dev/null; then
        local size
        size=$(du -sh "${BACKUP_DIR}/sends" | cut -f1)
        log_info "  -> Sends backed up ($size)"
        return 0
    else
        log_warn "  -> Failed to backup sends"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Rotate old backups (keep last N days)
# -----------------------------------------------------------------------------
rotate_backups() {
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would rotate backups older than ${RETENTION_DAYS} days"
        if [[ -d "$BACKUP_ROOT" ]]; then
            local old_dirs
            old_dirs=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" -mtime +${RETENTION_DAYS} 2>/dev/null || true)
            if [[ -n "$old_dirs" ]]; then
                echo "$old_dirs" | while read -r dir; do
                    [[ -n "$dir" ]] && log_info "[DRY-RUN] Would delete: $dir"
                done
            fi
        fi
        return 0
    fi
    
    log_info "Rotating backups older than ${RETENTION_DAYS} days..."
    
    if [[ ! -d "$BACKUP_ROOT" ]]; then
        log_info "  -> No backup root directory yet"
        return 0
    fi
    
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
}

# -----------------------------------------------------------------------------
# Generate backup manifest
# -----------------------------------------------------------------------------
generate_manifest() {
    if [[ "$DRY_RUN" == true ]]; then
        return 0
    fi
    
    local manifest="${BACKUP_DIR}/MANIFEST.txt"
    {
        echo "Vaultwarden Backup Manifest"
        echo "==========================="
        echo "Backup Date: $(date)"
        echo "Source: $VAULTWARDEN_DATA"
        echo "Backup Directory: $BACKUP_DIR"
        echo ""
        echo "Files:"
        ls -lh "$BACKUP_DIR" 2>/dev/null
        echo ""
        echo "Total Size:"
        du -sh "$BACKUP_DIR" 2>/dev/null
        echo ""
        echo "SHA256 Checksums:"
        cd "$BACKUP_DIR" && sha256sum *.sqlite3 *.pem *.der 2>/dev/null || echo "  (no checksums generated)"
    } > "$manifest"
    
    log_info "Manifest written to: $manifest"
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    local start_time
    start_time=$(date +%s)
    local errors=0
    
    echo "=============================================="
    echo "Vaultwarden Backup - ${DATE_STAMP}"
    echo "=============================================="
    
    if [[ "$DRY_RUN" == true ]]; then
        echo "(Running in DRY-RUN mode - no changes will be made)"
        echo ""
    fi
    
    # Pre-flight checks
    check_prerequisites
    
    # Create backup directory
    create_backup_dir
    
    # Backup components
    if ! backup_database; then
        ((errors++)) || true
    fi
    
    if ! backup_rsa_keys; then
        ((errors++)) || true
    fi
    
    if ! backup_attachments; then
        ((errors++)) || true
    fi
    
    if ! backup_sends; then
        ((errors++)) || true
    fi
    
    # Rotate old backups
    rotate_backups
    
    # Generate manifest
    generate_manifest
    
    # Final report
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    echo ""
    echo "=============================================="
    if [[ $errors -eq 0 ]]; then
        log_info "Backup completed successfully in ${duration}s"
        if [[ "$DRY_RUN" == false ]]; then
            log_info "Backup location: $BACKUP_DIR"
        fi
    else
        log_warn "Backup completed with ${errors} warning(s) in ${duration}s"
    fi
    echo "=============================================="
    
    # Exit with error count (0 = success)
    exit $errors
}

main "$@"
