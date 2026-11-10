const REFRESH_TOKEN_KEY = 'serverpulse.refreshToken'

let accessToken: string | null = null

export const tokenStore = {
  getAccessToken: (): string | null => accessToken,
  setAccessToken(token: string): void {
    accessToken = token
  },
  getRefreshToken: (): string | null => sessionStorage.getItem(REFRESH_TOKEN_KEY),
  setRefreshToken(token: string): void {
    sessionStorage.setItem(REFRESH_TOKEN_KEY, token)
  },
  clear(): void {
    accessToken = null
    sessionStorage.removeItem(REFRESH_TOKEN_KEY)
  },
}
