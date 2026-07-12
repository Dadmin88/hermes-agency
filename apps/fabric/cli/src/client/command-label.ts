export function buildCliCommandLabel(): string {
  const args = process.argv.slice(2);
  return args.length > 0 ? `hermes-fabric ${args.join(" ")}` : "hermes-fabric";
}
