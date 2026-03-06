{ pkgs, lib, config, ... }:

{
  # https://devenv.sh/basics/
  languages.python = {
    enable = true;
    # We use the default python3 from nixpkgs. 
    # If you need a specific version like 3.14, ensure it's available in your nixpkgs input.
  };

  # https://devenv.sh/packages/
  packages = [
    pkgs.python3Packages.paramiko
    pkgs.python3Packages.pyqt6
    pkgs.mutagen
    pkgs.qt6Packages.qtstyleplugin-kvantum
  ];

  env = {
    QT_STYLE_OVERRIDE = "kvantum";
  };

  # https://devenv.sh/scripts/
  scripts.main.exec = "python syncer.py";

  # https://devenv.sh/pre-commit-hooks/
  # pre-commit.hooks.shellcheck.enable = true;

  # https://devenv.sh/processes/
  # processes.ping.exec = "ping devenv.sh";

  # See full reference at https://devenv.sh/reference/options/
}
