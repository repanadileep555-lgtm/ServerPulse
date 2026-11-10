export interface HealthResponse {
  database: 'ok' | 'error'
}

export interface UserResponse {
  id: number
  username: string
  is_admin: boolean
  enabled: boolean
  created_at: string
}

export interface RegisterUserRequest {
  username: string
  password: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
}

export interface RefreshResponse {
  access_token: string
  token_type: 'bearer'
}
