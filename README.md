# Syncer

A Python GUI application for SFTP navigation and Mutagen session management.

## Features

- **SFTP Browser**: Navigate remote server file systems via SSH/SFTP
- **Forward Sessions**: Create Mutagen forwarding sessions from remote paths
- **Sync Sessions**: Create and manage Mutagen synchronization sessions
- **Session Management**: List, terminate, and monitor Mutagen sessions

## Requirements

- Python 3.8+
- paramiko (for SFTP)
- Mutagen (installed and in PATH)

## Installation

This project uses [pixi](https://pixi.sh) for dependency management.

```bash
# Install dependencies
pixi install

# Run the application
pixi run start

# Or run directly
pixi run python syncer.py
```

## Usage

### Connecting to a Server

1. Click "Connect" or press `Ctrl+N`
2. Enter SSH connection details:
   - Host: Server hostname or IP
   - Port: SSH port (default 22)
   - Username: SSH username
   - Password: SSH password (or use key file)
   - Key File: Path to SSH private key (optional)
3. Click "Connect"

### Navigating Remote Files

- Double-click folders to enter them
- Use the path entry to navigate directly
- Click "↑ Up" to go to parent directory
- Right-click files/folders for context menu

### Creating Mutagen Sessions

1. Navigate to desired remote path
2. Right-click a folder → "Create Forward/Sync Session"
3. Or use menu: Mutagen→ Create Forward/Sync Session
4. Fill in session details and click Create

### Managing Sessions

- View sessions in the right panel
- Switch between Forward and Sync tabs
- Click "Refresh" to update session list
- Select a session and click "Terminate" to remove it

## Keyboard Shortcuts

- `Ctrl+N` - New connection
- `Enter` in path field - Navigate to path

## Configuration

Connection settings are saved to `~/.syncer_config.json` for quick reconnection.

## License

MIT License