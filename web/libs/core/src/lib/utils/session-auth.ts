/** Optional authentication-only deployment hooks. Never replace fetch or editor behavior. */
declare global {
  interface Window {
    LSBridgeAuth?: {
      prepareRequest(headers: Headers, method: string, url: string): void;
      expired(): boolean;
    };
  }
}

export function prepareSessionRequest(headers: Headers, method: string, url: string) {
  if (typeof window !== "undefined") window.LSBridgeAuth?.prepareRequest(headers, method, url);
}

export function authenticationExpired(status: number) {
  return status === 401 && typeof window !== "undefined" && window.LSBridgeAuth?.expired() === true;
}
