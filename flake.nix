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
      devShells.${system}.default = devenv.lib.mkShell {
        inherit inputs pkgs;
        modules = [
          {
            # Fix "devenv was not able to determine the current directory" in CI
            # Explicitly convert path to string to avoid type error
            devenv.root = builtins.toString ./.;
          }
          ./devenv.nix
        ];
      };
    };
}
