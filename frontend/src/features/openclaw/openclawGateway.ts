export {
  generateDeviceIdentity,
  signDevicePayload,
} from './gateway/openclawDeviceIdentity'
export {
  OPENCLAW_CURRENT_SCOPES,
  OPENCLAW_LEGACY_SCOPES,
  GatewayRequestError,
  buildDeviceAuthPayloadV3,
  gatewaySupportsMethod,
  validateNegotiatedScopes,
  validateStoredOpenClawScopes,
} from './gateway/openclawGatewayProtocol'
export { OpenClawGatewayClient } from './gateway/openclawRpcClient'
export {
  parseOpenClawConnectionInput,
  validateGatewayUrl,
} from './gateway/openclawGatewayUrl'
export type {
  GatewayEvent,
  GatewayHello,
  GatewaySocket,
  OpenClawDeviceIdentity,
  OpenClawGatewayClientOptions,
} from './gateway/openclawGatewayTypes'
