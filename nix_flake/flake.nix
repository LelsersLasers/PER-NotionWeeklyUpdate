{
  description = "Python env";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      python = pkgs.python312;
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          (python.withPackages (ps: with ps; [
            notion-client
          ]))

          pkgs.mypy
        ];
      };
    };
}

