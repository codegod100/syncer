{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    devenv.url = "github:cachix/devenv";
  };

  outputs = { self, nixpkgs, devenv, ... } @ inputs:
    let
      # Use the current system. 
      # For a multi-platform flake, consider using `flake-utils`.
      system = "x86_64-linux"; 
      pkgs = nixpkgs.legacyPackages.${system};
    in
    let
      syncer-app = pkgs.writeShellApplication {
        name = "syncer";
        runtimeInputs = [
          (pkgs.python3.withPackages (ps: with ps; [
            paramiko
            pyqt6
          ]))
          pkgs.mutagen
          pkgs.qt6Packages.qtstyleplugin-kvantum
        ];
        text = ''
          export QT_STYLE_OVERRIDE="kvantum"
          python ${./syncer.py} "$@"
        '';
      };

      syncer-desktop = pkgs.makeDesktopItem {
        name = "syncer";
        desktopName = "Syncer";
        exec = "syncer";
        icon = "folder-remote"; # Standard icon for remote folders
        comment = "SFTP & Mutagen Manager";
        categories = [ "Development" "Network" ];
      };
    in
    {
      packages.${system}.default = pkgs.symlinkJoin {
        name = "syncer-with-desktop";
        paths = [
          syncer-app
          syncer-desktop
        ];
      };

      devShells.${system}.default = devenv.lib.mkShell {
        inherit inputs pkgs;
        modules = [
          {
            # Fix "devenv was not able to determine the current directory" in CI
            devenv.root = self.outPath;
          }
          ./devenv.nix
        ];
      };
    };
}
