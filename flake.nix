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
    {
      packages.${system}.default = pkgs.writeShellApplication {
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
