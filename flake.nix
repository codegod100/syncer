{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs = { self, nixpkgs, ... }:
    let
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
          export QT_PLUGIN_PATH="${pkgs.qt6Packages.qtstyleplugin-kvantum}/lib/qt-6/plugins"
          python ${./syncer.py} "$@"
        '';
      };

      syncer-desktop = pkgs.makeDesktopItem {
        name = "syncer";
        desktopName = "Syncer";
        exec = "syncer";
        icon = "folder-remote";
        comment = "SFTP & Mutagen Manager";
        categories = [ "Development" "Network" ];
      };
    in
    {
      packages.${system}.default = pkgs.stdenv.mkDerivation {
        name = "syncer";
        src = ./.;

        nativeBuildInputs = [ pkgs.copyDesktopItems ];

        desktopItems = [ syncer-desktop ];

        installPhase = ''
          mkdir -p $out/bin
          ln -s ${syncer-app}/bin/syncer $out/bin/syncer
          runHook postInstall
        '';
      };
    };
}
