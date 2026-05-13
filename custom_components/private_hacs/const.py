"""Constants for Private HACS."""

DOMAIN = "private_hacs"

# Storage
STORAGE_KEY = f"{DOMAIN}.repositories"
STORAGE_VERSION = 1

# Config entry keys
CONF_GITHUB_TOKEN = "github_token"
CONF_REPOS = "repositories"

# Per-repo keys
CONF_REPO = "repo"               # "owner/repo-name"
CONF_NAME = "name"               # Friendly name
CONF_COMPONENT_ID = "component_id"   # snake_case domain
CONF_BRANCH = "branch"           # default branch override (optional)

# GitHub API
GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_RELEASE_LATEST = "https://api.github.com/repos/{}/releases/latest"
GITHUB_API_RELEASES = "https://api.github.com/repos/{}/releases"
GITHUB_API_TAGS = "https://api.github.com/repos/{}/tags"
GITHUB_API_REPO = "https://api.github.com/repos/{}"
GITHUB_ARCHIVE_ZIP = "https://api.github.com/repos/{}/zipball/{}"

# Install state values
INSTALL_STATE_NOT_INSTALLED = "not_installed"
INSTALL_STATE_INSTALLED = "installed"
INSTALL_STATE_PENDING_RESTART = "pending_restart"

# Polling
DEFAULT_SCAN_INTERVAL_HOURS = 6

# Panel
PANEL_URL = "private-hacs"
PANEL_TITLE = "Private HACS"
PANEL_ICON = "mdi:shield-lock"
