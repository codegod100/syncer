#!/usr/bin/env python3
"""
Syncer - A GUI tool for SFTP navigation and Mutagen session management.

Features:
- SFTP browser to navigate remote server paths
- Create mutagen forward sessions
- Manage list mutagen sync sessions
"""

import sys
import os
import json
import getpass
import logging
import traceback
import subprocess
import signal

# Add system site-packages to sys.path to pick up system-installed PyQt6 (Kvantum theme)
# This avoids hardcoding Python version in pixi.toml
try:
    _sys_py = "/usr/bin/python3"
    if os.path.exists(_sys_py):
        _res = subprocess.run(
            [_sys_py, "-c", "import site; print(':'.join(site.getsitepackages()))"],
            capture_output=True, text=True, check=True
        )
        for _p in _res.stdout.strip().split(':'):
            if _p and _p not in sys.path:
                sys.path.append(_p)
except Exception:
    pass

from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QLabel, QPushButton,
    QLineEdit, QDialog, QDialogButtonBox, QComboBox, QRadioButton,
    QGroupBox, QPlainTextEdit, QMessageBox, QFileDialog, QMenu,
    QTabWidget, QMessageBox, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QAction, QCursor

import paramiko

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_gitignore(path: str) -> List[str]:
    """
    Parse .gitignore file and return list of ignore patterns.
    
    Args:
        path: Directory path to look for .gitignore
        
    Returns:
        List of ignore patterns suitable for mutagen
    """
    gitignore_path = os.path.join(path, '.gitignore')
    patterns = []
    
    if not os.path.exists(gitignore_path):
        logger.debug(f"No .gitignore found at {gitignore_path}")
        return patterns
    
    try:
        with open(gitignore_path, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Skip negation patterns (not supported by mutagen)
                if line.startswith('!'):
                    logger.debug(f"Skipping negation pattern: {line}")
                    continue
                # Convert .gitignore patterns to mutagen patterns
                patterns.append(line)
        
        logger.info(f"Parsed {len(patterns)} patterns from {gitignore_path}")
    except Exception as e:
        logger.error(f"Error parsing .gitignore: {e}")
    
    return patterns


def parse_ssh_config() -> List[Dict]:
    """
    Parse SSH config file and extract host configurations.
    
    Returns:
        List of host configurations with Host, HostName, User, Port, IdentityFile
    """
    config_path = os.path.expanduser("~/.ssh/config")
    hosts = []
    
    if not os.path.exists(config_path):
        logger.debug(f"SSH config not found at {config_path}")
        return hosts
    
    try:
        with open(config_path, 'r') as f:
            current_host = None
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Parse host declaration
                if line.lower().startswith('host '):
                    # Save previous host
                    if current_host and current_host.get('host'):
                        hosts.append(current_host)
                    # Start new host
                    host_aliases = line[5:].strip().split()
                    current_host = {
                        'host': host_aliases[0],
                        'hostname': host_aliases[0] if len(host_aliases) == 1 else host_aliases[0],
                        'user': '',
                        'port': 22,
                        'identity_file': ''
                    }
                elif current_host:
                    # Parse host properties
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        key = parts[0].lower()
                        value = parts[1].strip()
                        
                        if key == 'hostname':
                            current_host['hostname'] = value
                        elif key == 'user':
                            current_host['user'] = value
                        elif key == 'port':
                            try:
                                current_host['port'] = int(value)
                            except ValueError:
                                pass
                        elif key == 'identityfile':
                            current_host['identity_file'] = os.path.expanduser(value)
            
            # Don't forget the last host
            if current_host and current_host.get('host'):
                hosts.append(current_host)
        
        logger.info(f"Parsed {len(hosts)} hosts from SSH config")
        
    except Exception as e:
        logger.error(f"Error parsing SSH config: {e}")
    
    return hosts


@dataclass
class SSHConnection:
    """SSH connection parameters."""
    host: str
    port: int = 22
    username: str = ""
    password: str = ""
    key_path: Optional[str] = None


class SFTPBrowser:
    """Handles SFTP connection and file browsing."""
    
    def __init__(self):
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
        self.current_path = "/"
        self.connection: Optional[SSHConnection] = None
    
    def connect(self, conn: SSHConnection) -> Tuple[bool, str]:
        """
        Connect to SSH server and initialize SFTP.
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        logger.info(f"Attempting connection to {conn.username}@{conn.host}:{conn.port}")
        
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            kwargs = {
                'hostname': conn.host,
                'port': conn.port,
                'username': conn.username,
                'timeout': 30,
                'auth_timeout': 30,
            }
            
            auth_method = None
            if conn.key_path and os.path.exists(conn.key_path):
                kwargs['key_filename'] = conn.key_path
                auth_method = f"SSH key ({conn.key_path})"
                logger.info(f"Using SSH key authentication: {conn.key_path}")
            elif conn.password:
                kwargs['password'] = conn.password
                auth_method = "password"
                logger.info("Using password authentication")
            else:
                auth_method = "SSH agent / default keys"
                logger.info("Attempting SSH agent or default key authentication")
            
            logger.debug(f"Connection parameters: { {k: v for k, v in kwargs.items() if k != 'password'} }")
            
            self.client.connect(**kwargs)
            logger.info("SSH connection established successfully")
            
            self.sftp = self.client.open_sftp()
            logger.info("SFTP channel opened successfully")
            
            self.connection = conn
            self.current_path = self.sftp.normalize('.')
            
            msg = f"Connected to {conn.host}:{conn.port} as {conn.username} via {auth_method}"
            logger.info(msg)
            return True, msg
            
        except paramiko.AuthenticationException as e:
            error_msg = f"Authentication failed for {conn.username}@{conn.host}"
            logger.error(f"{error_msg}: {e}")
            self._cleanup_connection()
            return False, error_msg
            
        except paramiko.SSHException as e:
            error_msg = f"SSH error: {e}"
            logger.error(f"SSH error connecting to {conn.host}:{conn.port}: {e}")
            self._cleanup_connection()
            return False, error_msg
            
        except paramiko.BadHostKeyException as e:
            error_msg = f"Bad host key for {conn.host}. The server's host key has changed."
            logger.error(f"{error_msg}: {e}")
            self._cleanup_connection()
            return False, error_msg
            
        except ConnectionRefusedError:
            error_msg = f"Connection refused by {conn.host}:{conn.port}. Is SSH running?"
            logger.error(error_msg)
            self._cleanup_connection()
            return False, error_msg
            
        except TimeoutError:
            error_msg = f"Connection timeout to {conn.host}:{conn.port}"
            logger.error(error_msg)
            self._cleanup_connection()
            return False, error_msg
            
        except OSError as e:
            if "No route to host" in str(e):
                error_msg = f"No route to host {conn.host}. Check network connectivity."
            elif "Network is unreachable" in str(e):
                error_msg = f"Network is unreachable for {conn.host}"
            elif "Name or service not known" in str(e) or "hostname nor servname provided" in str(e):
                error_msg = f"Unknown host: {conn.host}. DNS lookup failed."
            else:
                error_msg = f"Network error: {e}"
            logger.error(f"{error_msg}")
            self._cleanup_connection()
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.error(f"Unexpected error connecting to {conn.host}:{conn.port}\n{traceback.format_exc()}")
            self._cleanup_connection()
            return False, error_msg
    
    def _cleanup_connection(self):
        """Clean up partial connection state."""
        if self.sftp:
            try:
                self.sftp.close()
            except:
                pass
            self.sftp = None
        if self.client:
            try:
                self.client.close()
            except:
                pass
            self.client = None
        self.connection = None
    
    def disconnect(self):
        """Disconnect from SSH server."""
        if self.sftp:
            try:
                self.sftp.close()
                logger.info("SFTP channel closed")
            except Exception as e:
                logger.warning(f"Error closing SFTP channel: {e}")
            self.sftp = None
        if self.client:
            try:
                self.client.close()
                logger.info("SSH connection closed")
            except Exception as e:
                logger.warning(f"Error closing SSH connection: {e}")
            self.client = None
        self.connection = None
    
    def is_connected(self) -> bool:
        """Check if connected to server."""
        return self.sftp is not None
    
    def list_dir(self, path: str = None) -> Tuple[List[Dict], Optional[str]]:
        """
        List directory contents.
        
        Returns:
            Tuple of (items, error_message)
        """
        if not self.sftp:
            return [], "Not connected to server"
        
        path = path or self.current_path
        items = []
        
        try:
            logger.debug(f"Listing directory: {path}")
            for entry in self.sftp.listdir_attr(path):
                item_type = "dir" if entry.st_mode & 0o040000 else "file"
                items.append({
                    'name': entry.filename,
                    'path': os.path.join(path, entry.filename),
                    'type': item_type,
                    'size': entry.st_size,
                    'mode': entry.st_mode,
                })
            items.sort(key=lambda x: (x['type'] != 'dir', x['name'].lower()))
            logger.debug(f"Listed {len(items)} items in {path}")
            return items, None
        except PermissionError:
            error_msg = f"Permission denied: {path}"
            logger.error(error_msg)
            return [], error_msg
        except FileNotFoundError:
            error_msg = f"Directory not found: {path}"
            logger.error(error_msg)
            return [], error_msg
        except Exception as e:
            error_msg = f"Error listing directory: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            return [], error_msg
    
    def change_dir(self, path: str) -> bool:
        """Change current directory."""
        try:
            new_path = self.sftp.normalize(path)
            self.sftp.stat(new_path)
            self.current_path = new_path
            return True
        except Exception as e:
            logger.error(f"Change dir error: {e}")
            return False
    
    def go_up(self):
        """Go to parent directory."""
        parent = os.path.dirname(self.current_path)
        if parent and parent != self.current_path:
            self.current_path = parent


class MutagenManager:
    """Manages mutagen sessions."""
    
    @staticmethod
    def run_command(args: List[str]) -> Tuple[int, str, str]:
        """Run a mutagen command and return output."""
        cmd = ['mutagen'] + args
        logger.debug(f"Running command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            logger.debug(f"Command returned code {result.returncode}")
            if result.returncode != 0:
                logger.warning(f"Command failed: {result.stderr}")
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            error_msg = "Command timed out after 60 seconds"
            logger.error(error_msg)
            return -1, "", error_msg
        except FileNotFoundError:
            error_msg = "mutagen command not found. Please install mutagen."
            logger.error(error_msg)
            return -1, "", error_msg
        except Exception as e:
            error_msg = f"Error running command: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            return -1, "", error_msg
    
    @staticmethod
    def _parse_sessions(output: str) -> List[Dict]:
        """Parse mutagen session list output."""
        sessions = []
        current = {}
        section = None  # Track which section we're in (source, destination, alpha, beta)
        
        for line in output.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            
            if stripped.startswith('---'):
                # Session separator
                if current and current.get('identifier'):
                    sessions.append(current)
                current = {}
                section = None
            elif stripped.startswith('Identifier:'):
                current['identifier'] = stripped.split(':', 1)[1].strip()
            elif stripped.startswith('Name:'):
                current['name'] = stripped.split(':', 1)[1].strip()
            elif stripped in ('Source:', 'Destination:', 'Alpha:', 'Beta:'):
                section = stripped.rstrip(':').lower()
            elif ':' in stripped and current:
                # Parse key: value
                key_val = stripped.split(':', 1)
                key = key_val[0].strip().lower()
                value = key_val[1].strip() if len(key_val) > 1 else ''
                
                if key == 'url' and section:
                    if section == 'source':
                        current['source'] = value
                    elif section == 'destination':
                        current['destination'] = value
                    elif section == 'alpha':
                        current['alpha'] = value
                    elif section == 'beta':
                        current['beta'] = value
                elif key == 'status':
                    current['status'] = value
        
        if current and current.get('identifier'):
            sessions.append(current)
        
        return sessions
    
    @staticmethod
    def list_forward_sessions() -> Tuple[List[Dict], str]:
        """
        List all forwarding sessions.
        
        Returns:
            Tuple of (sessions, error_message)
        """
        logger.debug("Listing forward sessions")
        code, stdout, stderr = MutagenManager.run_command(['forward', 'list'])
        
        if code != 0:
            return [], stderr
        
        sessions = MutagenManager._parse_sessions(stdout)
        logger.debug(f"Found {len(sessions)} forward sessions")
        return sessions, ""
    
    @staticmethod
    def list_sync_sessions() -> Tuple[List[Dict], str]:
        """
        List all synchronization sessions.
        
        Returns:
            Tuple of (sessions, error_message)
        """
        logger.debug("Listing sync sessions")
        code, stdout, stderr = MutagenManager.run_command(['sync', 'list'])
        
        if code != 0:
            return [], stderr
        
        sessions = MutagenManager._parse_sessions(stdout)
        logger.debug(f"Found {len(sessions)} sync sessions")
        return sessions, ""
    
    @staticmethod
    def create_forward_session(source: str, destination: str, name: str = None) -> Tuple[int, str, str]:
        """Create a forwarding session."""
        logger.info(f"Creating forward session '{name}': {source} -> {destination}")
        args = ['forward', 'create']
        if name:
            args.extend(['-n', name])
        args.extend([source, destination])
        return MutagenManager.run_command(args)
    
    @staticmethod
    def create_sync_session(alpha: str, beta: str, name: str = None, mode: str = None) -> Tuple[int, str, str]:
        """Create a synchronization session."""
        logger.info(f"Creating sync session '{name}': {alpha} <-> {beta}")
        args = ['sync', 'create']
        if name:
            args.extend(['-n', name])
        if mode:
            args.extend(['-m', mode])
        args.extend([alpha, beta])
        return MutagenManager.run_command(args)
    
    @staticmethod
    def terminate_forward_session(name: str) -> Tuple[int, str, str]:
        """Terminate a forwarding session."""
        return MutagenManager.run_command(['forward', 'terminate', name])
    
    @staticmethod
    def terminate_sync_session(name: str) -> Tuple[int, str, str]:
        """Terminate a synchronization session."""
        return MutagenManager.run_command(['sync', 'terminate', name])


class ConnectionDialog(QDialog):
    """Dialog for SSH connection settings."""
    
    def __init__(self, parent=None, initial_values: dict = None):
        super().__init__(parent)
        self.setWindowTitle("SSH Connection")
        self.setMinimumWidth(450)
        self.result: Optional[SSHConnection] = None
        self.initial_values = initial_values or {}
        self.ssh_hosts = parse_ssh_config()
        
        self._setup_ui()
        self._load_initial_values()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Saved Hosts dropdown
        host_group = QGroupBox("SSH Config Hosts")
        host_layout = QHBoxLayout(host_group)
        
        self.saved_host_combo = QComboBox()
        self.saved_host_combo.addItem("< Custom >")
        for h in self.ssh_hosts:
            self.saved_host_combo.addItem(h['host'])
        self.saved_host_combo.currentTextChanged.connect(self._on_host_selected)
        host_layout.addWidget(self.saved_host_combo)
        
        layout.addWidget(host_group)
        
        # Connection details
        details_group = QGroupBox("Connection Details")
        details_layout = QVBoxLayout(details_group)
        
        # Host and Port row
        host_row = QHBoxLayout()
        host_row.addWidget(QLabel("Host:"))
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("hostname or IP")
        host_row.addWidget(self.host_edit)
        host_row.addWidget(QLabel("Port:"))
        self.port_edit = QLineEdit("22")
        self.port_edit.setMaximumWidth(80)
        host_row.addWidget(self.port_edit)
        details_layout.addLayout(host_row)
        
        # Username row
        user_row = QHBoxLayout()
        user_row.addWidget(QLabel("Username:"))
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText(getpass.getuser())
        user_row.addWidget(self.username_edit)
        details_layout.addLayout(user_row)
        
        # Password row
        pass_row = QHBoxLayout()
        pass_row.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pass_row.addWidget(self.password_edit)
        details_layout.addLayout(pass_row)
        
        # Key file row
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Key File:"))
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("~/.ssh/id_rsa (optional)")
        key_row.addWidget(self.key_edit)
        key_btn = QPushButton("...")
        key_btn.setMaximumWidth(40)
        key_btn.clicked.connect(self._browse_key)
        key_row.addWidget(key_btn)
        details_layout.addLayout(key_row)
        
        layout.addWidget(details_group)
        
        # Buttons
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._on_connect)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.connect_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)
    
    def _on_host_selected(self, host_name: str):
        """Handle selection from saved hosts dropdown."""
        if host_name == "< Custom >":
            self.host_edit.clear()
            self.port_edit.setText("22")
            self.username_edit.setText(getpass.getuser())
            self.key_edit.clear()
            return
        
        for h in self.ssh_hosts:
            if h['host'] == host_name:
                self.host_edit.setText(h.get('hostname', host_name))
                self.port_edit.setText(str(h.get('port', 22)))
                self.username_edit.setText(h.get('user', '') or getpass.getuser())
                self.key_edit.setText(h.get('identity_file', ''))
                break
    
    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select SSH Key File",
            os.path.expanduser("~/.ssh"),
            "All Files (*);;PEM Files (*.pem)"
        )
        if path:
            self.key_edit.setText(path)
    
    def _load_initial_values(self):
        if self.initial_values:
            self.host_edit.setText(self.initial_values.get('host', ''))
            self.port_edit.setText(str(self.initial_values.get('port', 22)))
            self.username_edit.setText(self.initial_values.get('username', ''))
            self.key_edit.setText(self.initial_values.get('key_path', ''))
        
        if not self.username_edit.text().strip():
            self.username_edit.setText(getpass.getuser())
    
    def _on_connect(self):
        username = self.username_edit.text().strip() or getpass.getuser()
        host = self.host_edit.text().strip()
        
        if not host:
            QMessageBox.warning(self, "Error", "Host is required")
            return
        
        try:
            port = int(self.port_edit.text().strip() or 22)
        except ValueError:
            QMessageBox.warning(self, "Error", "Invalid port number")
            return
        
        self.result = SSHConnection(
            host=host,
            port=port,
            username=username,
            password=self.password_edit.text(),
            key_path=self.key_edit.text().strip() or None
        )
        self.accept()


class ForwardCreateDialog(QDialog):
    """Dialog for creating a forwarding session."""
    
    def __init__(self, parent=None, initial_remote_port: str = "", ssh_conn: SSHConnection = None):
        super().__init__(parent)
        self.setWindowTitle("Create Forward Session")
        self.setMinimumWidth(400)
        self.initial_remote_port = initial_remote_port
        self.ssh_conn = ssh_conn
        self.result = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Session name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Session Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("my-forward-session")
        name_row.addWidget(self.name_edit)
        layout.addLayout(name_row)
        
        # Local port
        local_row = QHBoxLayout()
        local_row.addWidget(QLabel("Local Port:"))
        self.local_port_edit = QLineEdit()
        self.local_port_edit.setPlaceholderText("8080")
        local_row.addWidget(self.local_port_edit)
        layout.addLayout(local_row)
        
        # Remote port
        remote_row = QHBoxLayout()
        remote_row.addWidget(QLabel("Remote Port:"))
        self.remote_port_edit = QLineEdit(self.initial_remote_port)
        self.remote_port_edit.setPlaceholderText("80")
        remote_row.addWidget(self.remote_port_edit)
        layout.addLayout(remote_row)
        
        # Direction
        direction_group = QGroupBox("Direction")
        direction_layout = QVBoxLayout(direction_group)
        
        self.local_to_remote = QRadioButton("Local → Remote (forward)")
        self.local_to_remote.setChecked(True)
        direction_layout.addWidget(self.local_to_remote)
        
        self.remote_to_local = QRadioButton("Remote → Local (reverse)")
        direction_layout.addWidget(self.remote_to_local)
        
        layout.addWidget(direction_group)
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_create)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def _on_create(self):
        name = self.name_edit.text().strip()
        local_port = self.local_port_edit.text().strip()
        remote_port = self.remote_port_edit.text().strip()
        
        if not local_port or not remote_port:
            QMessageBox.warning(self, "Error", "Both ports are required")
            return
        
        # Construct addresses
        local = f"tcp:localhost:{local_port}"
        remote = f"tcp:localhost:{remote_port}"
        
        # Build source/destination based on direction
        if self.ssh_conn:
            remote_str = f"{self.ssh_conn.username}@{self.ssh_conn.host}:{remote}"
        else:
            remote_str = remote
        
        if self.local_to_remote.isChecked():
            source = local
            destination = remote_str
        else:
            source = remote_str
            destination = local
        
        self.result = {
            'name': name,
            'source': source,
            'destination': destination
        }
        self.accept()


class SyncCreateDialog(QDialog):
    """Dialog for creating a sync session."""
    
    def __init__(self, parent=None, remote_path: str = "", ssh_conn: SSHConnection = None):
        super().__init__(parent)
        self.setWindowTitle("Create Sync Session")
        self.setMinimumWidth(550)
        self.remote_path = remote_path
        self.ssh_conn = ssh_conn
        self.result = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Session name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Session Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("my-sync-session")
        name_row.addWidget(self.name_edit)
        layout.addLayout(name_row)
        
        # Local path
        local_row = QHBoxLayout()
        local_row.addWidget(QLabel("Local Path:"))
        self.local_edit = QLineEdit()
        local_row.addWidget(self.local_edit)
        local_btn = QPushButton("...")
        local_btn.setMaximumWidth(40)
        local_btn.clicked.connect(self._browse_local)
        local_row.addWidget(local_btn)
        layout.addLayout(local_row)
        
        # Remote path
        remote_row = QHBoxLayout()
        remote_row.addWidget(QLabel("Remote Path:"))
        self.remote_edit = QLineEdit(self.remote_path)
        remote_row.addWidget(self.remote_edit)
        layout.addLayout(remote_row)
        
        # Sync mode
        mode_group = QGroupBox("Sync Mode")
        mode_layout = QVBoxLayout(mode_group)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "two-way-safe (conflict detection)",
            "two-way-resolved (conflict resolution)",
            "one-way-safe (alpha to beta)",
            "one-way-replica (mirror alpha to beta)"
        ])
        mode_layout.addWidget(self.mode_combo)
        
        layout.addWidget(mode_group)
        
        # Ignore options
        ignore_group = QGroupBox("Ignore Options")
        ignore_layout = QVBoxLayout(ignore_group)
        
        self.use_gitignore = QCheckBox("Use .gitignore patterns")
        self.use_gitignore.setChecked(True)
        self.use_gitignore.setToolTip("Automatically ignore files matching patterns in .gitignore")
        ignore_layout.addWidget(self.use_gitignore)
        
        self.ignore_vcs = QCheckBox("Ignore VCS directories (.git, .hg, .svn)")
        self.ignore_vcs.setChecked(True)
        ignore_layout.addWidget(self.ignore_vcs)
        
        layout.addWidget(ignore_group)
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_create)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def _browse_local(self):
        path = QFileDialog.getExistingDirectory(self, "Select Local Directory")
        if path:
            self.local_edit.setText(path)
    
    def _on_create(self):
        name = self.name_edit.text().strip()
        local = self.local_edit.text().strip()
        remote = self.remote_edit.text().strip()
        
        if not local or not remote:
            QMessageBox.warning(self, "Error", "Both paths are required")
            return
        
        # Build remote path string
        if self.ssh_conn:
            remote_str = f"{self.ssh_conn.username}@{self.ssh_conn.host}:{remote}"
        else:
            remote_str = remote
        
        mode_map = {
            "two-way-safe": "two-way-safe",
            "two-way-resolved": "two-way-resolved",
            "one-way-safe": "one-way-safe",
            "one-way-replica": "one-way-replica"
        }
        mode_text = self.mode_combo.currentText().split()[0]
        
        # Collect ignores
        ignores = []
        
        if self.use_gitignore.isChecked():
            gitignore_patterns = parse_gitignore(local)
            ignores.extend(gitignore_patterns)
        
        if self.ignore_vcs.isChecked():
            ignores.extend(['.git', '.hg', '.svn', '.bzr'])
        
        self.result = {
            'name': name,
            'alpha': local,
            'beta': remote_str,
            'mode': mode_map.get(mode_text, 'two-way-safe'),
            'ignores': ignores
        }
        self.accept()


class SyncerApp(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Syncer - SFTP & Mutagen Manager")
        self.setGeometry(100, 100, 1100, 750)
        
        self.sftp = SFTPBrowser()
        self.mutagen = MutagenManager()
        self.saved_connections: List[dict] = []
        self.last_connection: Optional[dict] = None
        self.config_file = os.path.expanduser("~/.syncer_config.json")
        
        self._load_config()
        self._create_menu()
        self._create_ui()
        
        # Prompt to reconnect to last session after UI is ready
        QTimer.singleShot(100, self._prompt_reconnect)
        
    def _load_config(self):
        """Load saved configuration."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.saved_connections = config.get('connections', [])
                    self.last_connection = config.get('last_connection')
        except Exception:
            pass
    
    def _save_config(self):
        """Save configuration."""
        try:
            config = {
                'connections': self.saved_connections,
                'last_connection': self.last_connection
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception:
            pass
    
    def _prompt_reconnect(self):
        """Prompt user to reconnect to last session on startup."""
        if not self.last_connection:
            return
        
        host = self.last_connection.get('host', 'unknown')
        username = self.last_connection.get('username', '')
        port = self.last_connection.get('port', 22)
        
        reply = QMessageBox.question(
            self,
            "Reconnect to Previous Session?",
            f"Do you want to reconnect to the previous session?\n\n"
            f"Host: {username}@{host}:{port}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._reconnect_last()
    
    def _create_menu(self):
        """Create menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        connect_action = QAction("&Connect...", self)
        connect_action.setShortcut("Ctrl+N")
        connect_action.triggered.connect(self._on_connect)
        file_menu.addAction(connect_action)
        
        disconnect_action = QAction("&Disconnect", self)
        disconnect_action.triggered.connect(self._on_disconnect)
        file_menu.addAction(disconnect_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Mutagen menu
        mutagen_menu = menubar.addMenu("&Mutagen")
        
        forward_action = QAction("Create &Forward Session...", self)
        forward_action.triggered.connect(self._create_forward)
        mutagen_menu.addAction(forward_action)
        
        sync_action = QAction("Create &Sync Session...", self)
        sync_action.triggered.connect(self._create_sync)
        mutagen_menu.addAction(sync_action)
        
        mutagen_menu.addSeparator()
        
        refresh_action = QAction("&Refresh Sessions", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._refresh_all_sessions)
        mutagen_menu.addAction(refresh_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _create_ui(self):
        """Create main UI."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QHBoxLayout(central_widget)
        
        # Splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left panel - SFTP Browser
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Connection status
        status_frame = QWidget()
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        self.status_label = QLabel("Not connected")
        status_layout.addWidget(self.status_label, 1)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._on_connect)
        status_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self._on_disconnect)
        self.disconnect_btn.setEnabled(False)
        status_layout.addWidget(self.disconnect_btn)
        
        left_layout.addWidget(status_frame)
        
        # Path entry
        path_frame = QWidget()
        path_layout = QHBoxLayout(path_frame)
        path_layout.setContentsMargins(0, 0, 0, 0)
        
        path_layout.addWidget(QLabel("Path:"))
        self.path_edit = QLineEdit("/")
        self.path_edit.returnPressed.connect(self._on_path_enter)
        path_layout.addWidget(self.path_edit)
        
        go_btn = QPushButton("Go")
        go_btn.clicked.connect(self._on_path_enter)
        path_layout.addWidget(go_btn)
        
        up_btn = QPushButton("Up")
        up_btn.clicked.connect(self._on_go_up)
        path_layout.addWidget(up_btn)
        
        left_layout.addWidget(path_frame)
        
        # File tree
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["Name", "Type", "Size"])
        self.file_tree.setColumnWidth(0, 250)
        self.file_tree.itemDoubleClicked.connect(self._on_file_double_click)
        self.file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self._on_file_context_menu)
        left_layout.addWidget(self.file_tree)
        
        splitter.addWidget(left_panel)
        
        # Right panel - Mutagen Sessions
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Tab widget for sessions
        tabs = QTabWidget()
        
        # Forward sessions tab
        forward_tab = QWidget()
        forward_layout = QVBoxLayout(forward_tab)
        
        forward_btn_frame = QWidget()
        forward_btn_layout = QHBoxLayout(forward_btn_frame)
        forward_btn_layout.setContentsMargins(0, 0, 0, 0)
        
        create_forward_btn = QPushButton("Create Forward")
        create_forward_btn.clicked.connect(self._create_forward)
        forward_btn_layout.addWidget(create_forward_btn)
        
        terminate_forward_btn = QPushButton("Terminate")
        terminate_forward_btn.clicked.connect(self._terminate_forward)
        forward_btn_layout.addWidget(terminate_forward_btn)
        
        forward_btn_layout.addStretch()
        
        refresh_forward_btn = QPushButton("Refresh")
        refresh_forward_btn.clicked.connect(self._refresh_forward)
        forward_btn_layout.addWidget(refresh_forward_btn)
        
        forward_layout.addWidget(forward_btn_frame)
        
        self.forward_tree = QTreeWidget()
        self.forward_tree.setHeaderLabels(["Name", "Source", "Destination", "Status"])
        self.forward_tree.setColumnWidth(0, 120)
        self.forward_tree.setColumnWidth(1, 200)
        self.forward_tree.setColumnWidth(2, 200)
        forward_layout.addWidget(self.forward_tree)
        
        tabs.addTab(forward_tab, "Forward Sessions")
        
        # Sync sessions tab
        sync_tab = QWidget()
        sync_layout = QVBoxLayout(sync_tab)
        
        sync_btn_frame = QWidget()
        sync_btn_layout = QHBoxLayout(sync_btn_frame)
        sync_btn_layout.setContentsMargins(0, 0, 0, 0)
        
        create_sync_btn = QPushButton("Create Sync")
        create_sync_btn.clicked.connect(self._create_sync)
        sync_btn_layout.addWidget(create_sync_btn)
        
        terminate_sync_btn = QPushButton("Terminate")
        terminate_sync_btn.clicked.connect(self._terminate_sync)
        sync_btn_layout.addWidget(terminate_sync_btn)
        
        sync_btn_layout.addStretch()
        
        refresh_sync_btn = QPushButton("Refresh")
        refresh_sync_btn.clicked.connect(self._refresh_sync)
        sync_btn_layout.addWidget(refresh_sync_btn)
        
        sync_layout.addWidget(sync_btn_frame)
        
        self.sync_tree = QTreeWidget()
        self.sync_tree.setHeaderLabels(["Name", "Alpha", "Beta", "Status"])
        self.sync_tree.setColumnWidth(0, 120)
        self.sync_tree.setColumnWidth(1, 200)
        self.sync_tree.setColumnWidth(2, 200)
        sync_layout.addWidget(self.sync_tree)
        
        tabs.addTab(sync_tab, "Sync Sessions")
        
        right_layout.addWidget(tabs)
        
        # Log output
        log_group = QGroupBox("Command Output")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QPlainTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_btn, alignment=Qt.AlignmentFlag.AlignRight)
        
        right_layout.addWidget(log_group)
        
        splitter.addWidget(right_panel)
        
        # Set splitter sizes
        splitter.setSizes([500, 600])
    
    def _log(self, message: str):
        """Log a message to the output area."""
        self.log_text.appendPlainText(message)
    
    def _update_connection_state(self, connected: bool):
        """Update UI based on connection state."""
        if connected:
            self.status_label.setText(f"Connected to {self.sftp.connection.host}")
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self._refresh_file_list()
        else:
            self.status_label.setText("Not connected")
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            self.path_edit.setText("/")
            self.file_tree.clear()
    
    def _reconnect_last(self):
        """Reconnect using the last saved connection."""
        if not self.last_connection:
            return
        
        conn = SSHConnection(
            host=self.last_connection.get('host', ''),
            port=self.last_connection.get('port', 22),
            username=self.last_connection.get('username', ''),
            key_path=self.last_connection.get('key_path')
        )
        
        self._log(f"Reconnecting to {conn.host}:{conn.port} as {conn.username}...")
        success, message = self.sftp.connect(conn)
        
        if success:
            self._update_connection_state(True)
            self._log(f"✓ {message}")
            self._log(f"Current directory: {self.sftp.current_path}")
            self.path_edit.setText(self.sftp.current_path)
            self._refresh_all_sessions()
        else:
            self._log(f"✗ Reconnection failed: {message}")
            QMessageBox.critical(self, "Connection Error", f"Failed to reconnect:\n\n{message}")
    
    def _on_connect(self):
        """Handle connect button."""
        initial = {}
        if self.sftp.connection:
            initial = {
                'host': self.sftp.connection.host,
                'port': self.sftp.connection.port,
                'username': self.sftp.connection.username,
                'key_path': self.sftp.connection.key_path
            }
        
        dialog = ConnectionDialog(self, initial)
        if dialog.exec():
            conn = dialog.result
            self._log(f"Connecting to {conn.host}:{conn.port} as {conn.username}...")
            
            success, message = self.sftp.connect(conn)
            
            if success:
                self._update_connection_state(True)
                self._log(f"✓ {message}")
                self._log(f"Current directory: {self.sftp.current_path}")
                self.path_edit.setText(self.sftp.current_path)
                
                # Save connection and remember as last used
                conn_dict = {
                    'host': conn.host,
                    'port': conn.port,
                    'username': conn.username,
                    'key_path': conn.key_path
                }
                if conn_dict not in self.saved_connections:
                    self.saved_connections.append(conn_dict)
                self.last_connection = conn_dict
                self._save_config()
                self._refresh_all_sessions()
            else:
                self._log(f"✗ Connection failed: {message}")
                QMessageBox.critical(self, "Connection Error", f"Failed to connect:\n\n{message}")
    
    def _on_disconnect(self):
        """Handle disconnect button."""
        self.sftp.disconnect()
        self._update_connection_state(False)
        self._log("Disconnected")
    
    def _refresh_file_list(self):
        """Refresh the file listing."""
        self.file_tree.clear()
        
        if not self.sftp.is_connected():
            return
        
        items, error = self.sftp.list_dir()
        
        if error:
            self._log(f"✗ {error}")
            QMessageBox.critical(self, "Directory Error", error)
            return
        
        for item in items:
            size_str = ""
            if item['type'] == 'file':
                size = item['size']
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size/1024:.1f} KB"
                else:
                    size_str = f"{size/1024/1024:.1f} MB"
            
            tree_item = QTreeWidgetItem([item['name'], item['type'], size_str])
            
            # Set icon based on type
            if item['type'] == 'dir':
                tree_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon))
            else:
                tree_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon))
            
            self.file_tree.addTopLevelItem(tree_item)
        
        self._log(f"Listed {len(items)} items in {self.sftp.current_path}")
    
    def _on_path_enter(self):
        """Handle path entry."""
        path = self.path_edit.text()
        if self.sftp.change_dir(path):
            self.path_edit.setText(self.sftp.current_path)
            self._refresh_file_list()
        else:
            QMessageBox.warning(self, "Error", f"Cannot access path: {path}")
    
    def _on_go_up(self):
        """Go to parent directory."""
        if self.sftp.is_connected():
            self.sftp.go_up()
            self.path_edit.setText(self.sftp.current_path)
            self._refresh_file_list()
    
    def _on_file_double_click(self, item: QTreeWidgetItem, column: int):
        """Handle double-click on file."""
        name = item.text(0)
        item_type = item.text(1)
        
        if item_type == 'dir':
            new_path = os.path.join(self.sftp.current_path, name)
            if self.sftp.change_dir(new_path):
                self.path_edit.setText(self.sftp.current_path)
                self._refresh_file_list()
    
    def _on_file_context_menu(self, position):
        """Show context menu for files."""
        item = self.file_tree.itemAt(position)
        if not item:
            return
        
        name = item.text(0)
        item_type = item.text(1)
        
        menu = QMenu()
        
        if item_type == 'dir':
            sync_action = menu.addAction(f"Create Sync Session from '{name}'")
            sync_action.triggered.connect(lambda: self._create_sync_from_path(name, item_type))
        
        copy_action = menu.addAction("Copy Path")
        copy_action.triggered.connect(lambda: self._copy_path(name))
        
        menu.exec(QCursor.pos())
    
    def _copy_path(self, name: str):
        """Copy full path to clipboard."""
        path = os.path.join(self.sftp.current_path, name)
        QApplication.clipboard().setText(path)
        self._log(f"Copied: {path}")
    
    def _get_selected_remote_path(self) -> str:
        """Get the currently selected remote path or current directory."""
        item = self.file_tree.currentItem()
        if item:
            name = item.text(0)
            item_type = item.text(1)
            if item_type == 'dir':
                return os.path.join(self.sftp.current_path, name)
        return self.sftp.current_path
    
    def _create_sync_from_path(self, name: str, item_type: str):
        """Create sync session from a path."""
        path = os.path.join(self.sftp.current_path, name)
        self._create_sync(default_path=path)
    
    def _create_forward(self, default_addr: str = ""):
        """Create a new forwarding session."""
        if not isinstance(default_addr, str):
            default_addr = ""
            
        if not self.sftp.is_connected():
            QMessageBox.warning(self, "Warning", "Please connect to a server first")
            return
        
        dialog = ForwardCreateDialog(self, default_addr, self.sftp.connection)
        if dialog.exec():
            self._log(f"Creating forward session '{dialog.result['name']}'...")
            code, stdout, stderr = MutagenManager.create_forward_session(
                dialog.result['source'],
                dialog.result['destination'],
                dialog.result['name']
            )
            
            if code == 0:
                self._log(f"✓ Session created successfully")
                self._refresh_forward()
            else:
                self._log(f"✗ Error: {stderr}")
                QMessageBox.critical(self, "Error", f"Failed to create session:\n\n{stderr}")
    
    def _create_sync(self, default_path: str = ""):
        """Create a new sync session."""
        if not isinstance(default_path, str):
            default_path = ""
            
        if not self.sftp.is_connected():
            QMessageBox.warning(self, "Warning", "Please connect to a server first")
            return
        
        if not default_path:
            default_path = self._get_selected_remote_path()
        
        dialog = SyncCreateDialog(self, default_path, self.sftp.connection)
        if dialog.exec():
            session_name = dialog.result['name']
            self._log(f"Creating sync session '{session_name}'...")
            args = ['sync', 'create']
            if session_name:
                args.extend(['-n', session_name])
            args.extend(['-m', dialog.result['mode']])
            
            # Add ignore patterns
            ignores = dialog.result.get('ignores', [])
            if ignores:
                self._log(f"  Ignoring {len(ignores)} patterns from .gitignore and VCS")
                for pattern in ignores:
                    args.extend(['-i', pattern])
            
            args.extend([dialog.result['alpha'], dialog.result['beta']])
            
            code, stdout, stderr = MutagenManager.run_command(args)
            
            if code == 0:
                self._log(f"✓ Session created successfully")
                self._refresh_sync()
            else:
                self._log(f"✗ Error: {stderr}")
                QMessageBox.critical(self, "Error", f"Failed to create session:\n\n{stderr}")
    
    def _refresh_forward(self):
        """Refresh forward sessions list."""
        self.forward_tree.clear()
        sessions, error = MutagenManager.list_forward_sessions()
        
        if error:
            self._log(f"✗ Error listing forward sessions: {error}")
            return
        
        for session in sessions:
            # Use name if available, otherwise show identifier
            display_name = session.get('name') or session.get('identifier', '')
            item = QTreeWidgetItem([
                display_name,
                session.get('source', ''),
                session.get('destination', ''),
                session.get('status', '')
            ])
            self.forward_tree.addTopLevelItem(item)
        
        self._log(f"Listed {len(sessions)} forward sessions")
    
    def _refresh_sync(self):
        """Refresh sync sessions list."""
        self.sync_tree.clear()
        sessions, error = MutagenManager.list_sync_sessions()
        
        if error:
            self._log(f"✗ Error listing sync sessions: {error}")
            return
        
        for session in sessions:
            # Use name if available, otherwise show identifier
            display_name = session.get('name') or session.get('identifier', '')
            item = QTreeWidgetItem([
                display_name,
                session.get('alpha', ''),
                session.get('beta', ''),
                session.get('status', '')
            ])
            self.sync_tree.addTopLevelItem(item)
        
        self._log(f"Listed {len(sessions)} sync sessions")
    
    def _refresh_all_sessions(self):
        """Refresh both session lists."""
        self._refresh_forward()
        self._refresh_sync()
    
    def _terminate_forward(self):
        """Terminate selected forward session."""
        item = self.forward_tree.currentItem()
        if not item:
            QMessageBox.warning(self, "Warning", "Please select a session to terminate")
            return
        
        name = item.text(0)
        
        reply = QMessageBox.question(
            self, "Confirm",
            f"Terminate session '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._log(f"Terminating forward session '{name}'...")
            code, stdout, stderr = MutagenManager.terminate_forward_session(name)
            if code == 0:
                self._log(f"✓ Session terminated")
                self._refresh_forward()
            else:
                self._log(f"✗ Error: {stderr}")
    
    def _terminate_sync(self):
        """Terminate selected sync session."""
        item = self.sync_tree.currentItem()
        if not item:
            QMessageBox.warning(self, "Warning", "Please select a session to terminate")
            return
        
        name = item.text(0)
        
        reply = QMessageBox.question(
            self, "Confirm",
            f"Terminate session '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._log(f"Terminating sync session '{name}'...")
            code, stdout, stderr = MutagenManager.terminate_sync_session(name)
            if code == 0:
                self._log(f"✓ Session terminated")
                self._refresh_sync()
            else:
                self._log(f"✗ Error: {stderr}")
    
    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self, "About Syncer",
            "Syncer - SFTP & Mutagen Manager\n\n"
            "A GUI tool for:\n"
            "• Navigating remote servers via SFTP\n"
            "• Creating Mutagen forwarding sessions\n"
            "• Managing Mutagen sync sessions\n\n"
            "Version 1.0"
        )
    
    def closeEvent(self, event):
        """Handle application close."""
        if self.sftp.is_connected():
            self.sftp.disconnect()
        self._save_config()
        event.accept()


def main():
    """Main entry point."""
    # Allow Ctrl+C to stop the application
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    app = QApplication(sys.argv)
    
    # Optional: A timer to periodically run the Python interpreter to catch signals
    # Not strictly needed with SIG_DFL, but good practice for cleaner exits
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)
    
    window = SyncerApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()