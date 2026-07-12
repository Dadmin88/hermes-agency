import { SECRET_PROVIDERS, type SecretProvider } from "@hermes-fabric/shared";
import { fabricEnv } from "../fabric-env.js";

export function getConfiguredSecretProvider(): SecretProvider {
  const configuredProvider = fabricEnv("SECRETS_PROVIDER");
  return configuredProvider && SECRET_PROVIDERS.includes(configuredProvider as SecretProvider)
    ? configuredProvider as SecretProvider
    : "local_encrypted";
}
